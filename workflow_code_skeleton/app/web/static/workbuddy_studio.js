(function () {
  const config = window.workbuddyStudioConfig || {};
  const skillNames = {
    overall_dispatcher: "总质检调度器",
    character_continuity: "人物连续性审查器",
    hook_rhythm: "爽点节奏审查员",
    logic_holes: "逻辑漏洞审查员",
    character_humanity: "人物人情味优化师",
    character_resonance: "人物画像共鸣评估师",
  };
  const skillGoalOptions = {
    overall_dispatcher: {
      hint: "总质检会先判断整部剧最大短板，并给出优先修复顺序。",
      options: [
        "先找出最影响成片质量的问题",
        "按优先级列出必须先修的集数和问题",
        "重点检查缺集、短集、重复集和结构断层",
        "评估这部剧是否具备继续打磨价值",
      ],
    },
    character_continuity: {
      hint: "人物连续性会重点检查角色动机、关系变化、角色消失和行为反常。",
      options: [
        "重点检查人物线是否断裂",
        "找出角色突然消失或戏份断档的问题",
        "检查主角、反派、关键配角的动机是否前后一致",
        "检查人物关系转变是否有铺垫和兑现",
      ],
    },
    hook_rhythm: {
      hint: "爽点节奏会检查开篇为什么让人继续读、段落与集尾钩子、信息缺口、语言节奏和爽点兑现。",
      options: [
        "重点优化开篇阅读钩子和文字质感",
        "检查前300字和前三集是否让人继续读",
        "找出集尾钩子弱、反转不足的集数",
        "检查段落钩子、语言节奏和爽点兑现",
      ],
    },
    logic_holes: {
      hint: "逻辑漏洞会重点检查设定冲突、因果断裂、信息差错误和伏笔未回收。",
      options: [
        "重点检查逻辑漏洞和前后矛盾",
        "找出设定冲突、规则变化和信息差错误",
        "检查关键事件的因果链是否成立",
        "检查伏笔、道具、秘密是否有回收",
      ],
    },
    character_humanity: {
      hint: "人物人情味会检查角色有没有真实的内心波动、生活质感、矛盾反应和不直说的潜台词。",
      options: [
        "让主要人物更真实、更有人情味",
        "丰富关键场景的内心活动和身体反应",
        "减少口号式心理描写和工具人对白",
        "为情感转折补足细节、潜台词和记忆触发",
      ],
    },
    character_resonance: {
      hint: "画像共鸣会判断目标读者能否理解人物、在意人物，并愿意跟随人物继续看下去。",
      options: [
        "评估主角画像是否足够吸引人",
        "找出读者最容易共鸣和最容易出戏的位置",
        "增强人物的欲望、软肋、矛盾和选择代价",
        "让反派和配角也有辨识度与可理解动机",
      ],
    },
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  let activeSkill = "overall_dispatcher";
  let activeModel = "";
  let modelPickerExpanded = false;
  let cachedModels = [];
  let cachedDefaultModel = "";
  let currentHistoryItems = [];
  let runningTimer = null;
  let uploadedWordSource = { id: "", filename: "", scriptSnapshot: "" };
  let currentOptimizationContext = null;
  const apiConfigStorageKey = "workbuddy.scriptDoctor.apiConfig.v1";

  function authHeaders() {
    return config.authToken ? { Authorization: `Bearer ${config.authToken}` } : {};
  }

  function readApiConfig() {
    try {
      const raw = window.localStorage.getItem(apiConfigStorageKey);
      if (!raw) return { apiKey: "", internetEnvironment: "internal" };
      const parsed = JSON.parse(raw);
      return {
        apiKey: String(parsed.apiKey || "").trim(),
        internetEnvironment: String(parsed.internetEnvironment || "internal").trim() || "internal",
      };
    } catch (error) {
      return { apiKey: "", internetEnvironment: "internal" };
    }
  }

  function saveApiConfig(value) {
    window.localStorage.setItem(apiConfigStorageKey, JSON.stringify({
      apiKey: String(value.apiKey || "").trim(),
      internetEnvironment: String(value.internetEnvironment || "internal").trim() || "internal",
      updatedAt: new Date().toISOString(),
    }));
  }

  function clearApiConfig() {
    window.localStorage.removeItem(apiConfigStorageKey);
  }

  function codebuddyHeaders() {
    const apiConfig = readApiConfig();
    const headers = authHeaders();
    if (apiConfig.apiKey) headers["X-CodeBuddy-Api-Key"] = apiConfig.apiKey;
    if (apiConfig.internetEnvironment) headers["X-CodeBuddy-Internet-Environment"] = apiConfig.internetEnvironment;
    if (activeModel && activeModel !== "auto") headers["X-CodeBuddy-Model"] = activeModel;
    return headers;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function pretty(value) {
    if (typeof value === "string") return value;
    return JSON.stringify(value, null, 2);
  }

  function setResult(value) {
    $("#wbResultBox").textContent = pretty(value);
    renderReportView(value);
  }

  function setRunningResult(payload) {
    currentOptimizationContext = null;
    $("#wbResultBox").textContent = "AI 剧本医生正在分析剧本，请稍候。";
    renderRunningView(payload);
  }

  function renderRunningView(payload = {}) {
    const root = $("#wbReportView");
    if (!root) return;
    const skillName = skillNames[payload.skill] || skillNames[activeSkill] || "剧本医生";
    const steps = runningStepsForSkill(payload.skill || activeSkill);
    const scriptLength = (payload.script_text || "").length;
    const longHint = scriptLength > 30000
      ? "当前剧本文本较长，人物线或逻辑审查可能需要 5-8 分钟。请保持页面打开。"
      : "正在拆分剧本、识别集数、定位问题并整理修订建议。页面没有卡住。";
    root.innerHTML = `
      <section class="wb-running-card" aria-live="polite">
        <div class="wb-running-orbit">
          <span></span><span></span><span></span>
        </div>
        <div class="wb-running-copy">
          <p class="wb-section-label">RUNNING</p>
          <h3>${escapeHtml(skillName)}正在体检</h3>
          <p>${escapeHtml(longHint)}</p>
        </div>
        <div class="wb-running-steps">
          ${steps.map((item, index) => `<span class="${index === 0 ? "is-active" : ""}">${escapeHtml(item)}</span>`).join("")}
        </div>
      </section>
    `;
    let activeIndex = 0;
    clearRunningTimer();
    runningTimer = window.setInterval(() => {
      const nodes = $$(".wb-running-steps span", root);
      if (!nodes.length) return;
      activeIndex = (activeIndex + 1) % nodes.length;
      nodes.forEach((node, index) => node.classList.toggle("is-active", index === activeIndex));
    }, 1800);
  }

  function clearRunningTimer() {
    if (runningTimer) {
      window.clearInterval(runningTimer);
      runningTimer = null;
    }
  }

  function runningStepsForSkill(skillKey) {
    const shared = ["读取正文", "识别集数", "整理报告"];
    const map = {
      overall_dispatcher: ["拆分分集", "判断缺集", "评分风险", "排序修复"],
      character_continuity: ["提取人物", "检查动机", "追踪关系", "定位断线"],
      hook_rhythm: ["审查开篇", "定位缺口", "检查文采", "扫描集尾"],
      logic_holes: ["提取规则", "检查因果", "核对信息差", "定位漏洞"],
      character_humanity: ["读取内心", "核对情绪", "检查文风", "生成样例"],
      character_resonance: ["提取画像", "匹配受众", "评估共鸣", "增强吸引"],
    };
    return map[skillKey] || shared;
  }

  function parseReportPayload(value) {
    if (!value) return null;
    if (typeof value === "string") return parseLooseJson(value);
    if (value.report) return parseLooseJson(value.report) || parseLooseJson(value.structured_output) || value.structured_output || null;
    if (value.structured_output) return value.structured_output;
    if (value.doctor_type || value.score || value.global_issues || value.episode_audit || value.episode_map || value.issue || value.issues) return value;
    return null;
  }

  function parseLooseJson(text) {
    if (text && typeof text === "object") return text;
    if (typeof text !== "string") return null;
    const trimmed = text.trim();
    if (!trimmed) return null;
    const candidates = [
      trimmed,
      trimmed.replace(/\\"/g, '"').replace(/\\n/g, "\n").replace(/\\t/g, "\t"),
    ];
    for (const candidate of candidates) {
      const parsed = tryParseJson(candidate);
      if (parsed) return parsed;
      const start = candidate.indexOf("{");
      const end = candidate.lastIndexOf("}");
      if (start >= 0 && end > start) {
        const sliced = tryParseJson(candidate.slice(start, end + 1));
        if (sliced) return sliced;
      }
    }
    return null;
  }

  function tryParseJson(text) {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed === "string") return parseLooseJson(parsed);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (error) {
      return null;
    }
  }

  function renderReportView(value) {
    clearRunningTimer();
    const root = $("#wbReportView");
    if (!root) return;
    if (value && typeof value === "object" && value.ok === false) {
      renderErrorView(value, root);
      return;
    }
    const report = parseReportPayload(value);
    if (!report) {
      root.innerHTML = '<div class="wb-report-empty">运行体检后，这里会展示总评分、风险等级、分集问题地图和优先修订建议。</div>';
      return;
    }

    const normalized = normalizeDoctorReport(report);
    const episodeSizeClass = episodeMapSizeClass(normalized.episodes.length);
    const episodeMap = normalized.episodes.length
      ? normalized.episodes.slice(0, 120).map((item) => {
          const title = `第${item.episode}集 · ${statusLabel(item.status)}${item.main_issue ? " · " + item.main_issue : ""}`;
          const hasIssue = normalized.issues.some((issue) => Number(issue.episode) === Number(item.episode));
          return `<button class="wb-episode-dot is-${escapeHtml(item.status)}${hasIssue ? " has-target" : ""}" type="button" title="${escapeHtml(title)}" data-episode="${escapeHtml(item.episode)}">${escapeHtml(item.episode)}</button>`;
        }).join("")
      : '<span class="wb-report-muted">未识别到分集编号</span>';

    const globalIssues = normalized.globalIssues.slice(0, 8);
    const episodeIssues = normalized.issues.filter((issue) => issue.episode).slice(0, 80);
    const fallbackIssues = normalized.issues.filter((issue) => !issue.episode).slice(0, 8);
    const priorities = normalized.priorityFixes.slice(0, 8);
    const diagnosis = report.one_sentence_diagnosis || report.summary || "未返回一句话诊断。";
    const score = normalized.score ?? "未评分";
    const risk = normalized.risk || "unknown";
    const issueCount = normalized.issues.length || globalIssues.length || 0;
    const optimizationPanel = currentOptimizationContext && currentOptimizationContext.canOptimize
      ? `<section class="wb-optimize-panel">
          <div>
            <p class="wb-section-label">ONE-CLICK OPTIMIZE</p>
            <h3>按本次报告优化原 Word</h3>
            <p>只回写通过原文匹配校验的段落，不覆盖原文件。完成后自动下载新的 DOCX。</p>
            <small id="wbOptimizeStatus">已绑定：${escapeHtml(currentOptimizationContext.filename || "原始剧本.docx")}</small>
          </div>
          <button class="wb-primary-btn wb-optimize-btn" type="button" data-report-action="optimize">一键优化并下载</button>
        </section>`
      : "";

    root.innerHTML = `
      <section class="wb-report-summary">
        <div class="wb-score-card">
          <span>总评分</span>
          <strong>${escapeHtml(score)}</strong>
        </div>
        <div>
          <span>风险等级</span>
          <strong class="wb-risk is-${escapeHtml(String(risk).toLowerCase())}">${escapeHtml(risk)}</strong>
        </div>
        <div>
          <span>识别集数</span>
          <strong>${escapeHtml(normalized.detectedEpisodeCount || "未识别")}</strong>
        </div>
        <div>
          <span>问题数量</span>
          <strong>${escapeHtml(issueCount || "0")}</strong>
        </div>
      </section>
      ${optimizationPanel}
      <section class="wb-report-block">
        <h3>一句话诊断</h3>
        <p>${escapeHtml(diagnosis)}</p>
      </section>
      <section class="wb-report-block">
        <div class="wb-report-block-head">
          <h3>分集问题地图</h3>
        </div>
        <div class="wb-episode-map ${episodeSizeClass}">${episodeMap}</div>
        <div class="wb-episode-legend" aria-label="分集状态说明">
          <span class="is-good">绿=正常</span>
          <span class="is-warning">黄=需修</span>
          <span class="is-danger">红=严重/缺失</span>
          <span class="is-unknown">灰=重复/未知</span>
        </div>
      </section>
      <details class="wb-report-block wb-collapsible-block wb-report-priority" open>
        <summary>
          <span>优先修复路径</span>
          <em>${escapeHtml(priorities.length || 0)} 项</em>
        </summary>
        <div class="wb-priority-list">
          ${priorities.length ? priorities.map(renderPriorityCard).join("") : '<div class="wb-report-empty">本次报告没有返回优先修复路径。</div>'}
        </div>
      </details>
      <details class="wb-report-block wb-collapsible-block" open>
        <summary>
          <span>核心问题与修订建议</span>
          <em>${escapeHtml((globalIssues.length || fallbackIssues.length || 0))} 项</em>
        </summary>
        <div class="wb-issue-list">
          ${globalIssues.length ? globalIssues.map((issue) => renderIssueCard(issue, "global")).join("") : fallbackIssues.map((issue) => renderIssueCard(issue, "global")).join("") || '<div class="wb-report-empty">本次报告没有返回可解析的核心问题。</div>'}
        </div>
      </details>
      <details class="wb-report-block wb-collapsible-block" id="wbEpisodeIssuePanel">
        <summary>
          <span>分集问题定位</span>
          <em>${escapeHtml(episodeIssues.length || 0)} 集/条</em>
        </summary>
        <p class="wb-block-tip">点击上方分集圆点，会自动展开这里并定位到对应问题。</p>
        <div class="wb-episode-issue-list">
          ${episodeIssues.length ? episodeIssues.map((issue) => renderIssueCard(issue, "episode")).join("") : '<div class="wb-report-empty">没有识别到按集归属的问题。若报告来自旧记录，建议重新运行一次。</div>'}
        </div>
      </details>
    `;
    bindEpisodeMap(root);
  }

  function renderErrorView(value, root) {
    const payload = value.accepted_payload || {};
    root.innerHTML = `
      <section class="wb-error-card">
        <div class="wb-error-icon">!</div>
        <div>
          <p class="wb-section-label">FAILED</p>
          <h3>${escapeHtml(value.error || "剧本医生调用失败")}</h3>
          <p>剧本标题：${escapeHtml(payload.title || "未命名")} · 字数：${escapeHtml(payload.script_length || 0)} · Skill：${escapeHtml(skillNames[payload.skill] || payload.skill || "")}</p>
          ${payload.timeout_seconds ? `<p>本次等待上限：${escapeHtml(payload.timeout_seconds)} 秒。长剧本建议保留页面，必要时拆分前半/后半分别体检。</p>` : ""}
        </div>
      </section>
    `;
  }

  function episodeMapSizeClass(count) {
    if (count <= 12) return "is-few";
    if (count <= 36) return "is-medium";
    if (count <= 80) return "is-many";
    return "is-dense";
  }

  function normalizeDoctorReport(report) {
    const integrity = report.episode_integrity || {};
    const rawEpisodeItems = firstArray(
      report.episode_map,
      report.episode_audit,
      report.episode_reports,
      report.episodes,
      report.issue,
      report.issues
    );
    const missing = normalizeNumberList(integrity.missing_episodes);
    const shortOrEmpty = normalizeNumberList(integrity.short_or_empty_episodes);
    const duplicate = normalizeNumberList(integrity.duplicate_episodes);
    const itemEpisodes = rawEpisodeItems.map((item) => readEpisodeNumber(item)).filter(Boolean);
    const maxEpisode = Math.max(
      Number(report.detected_episode_count || report.episode_count || report.total_episodes || 0),
      ...missing,
      ...shortOrEmpty,
      ...duplicate,
      ...itemEpisodes,
      0
    );
    const itemByEpisode = new Map();
    rawEpisodeItems.forEach((item) => {
      const episode = readEpisodeNumber(item);
      if (episode) itemByEpisode.set(episode, item);
    });
    const episodes = maxEpisode
      ? Array.from({ length: Math.min(maxEpisode, 120) }, (_, index) => {
          const episode = index + 1;
          const item = itemByEpisode.get(episode) || {};
          return {
            episode,
            status: normalizeEpisodeStatus(
              item.status || item.rhythm_status || item.ending_status || item.hook_status,
              { missing: missing.includes(episode), shortOrEmpty: shortOrEmpty.includes(episode), duplicate: duplicate.includes(episode) }
            ),
            main_issue: item.main_issue || item.issue || item.current_problem || item.current_ending_problem || item.payoff_issue || "",
          };
        })
      : [];
    return {
      score: report.score ?? report.total_score ?? report.overall_score,
      risk: report.risk_level || report.risk || report.riskLevel || "",
      detectedEpisodeCount: report.detected_episode_count || report.episode_count || report.total_episodes || maxEpisode || "",
      episodes,
      issues: normalizeIssues(report, rawEpisodeItems),
      globalIssues: normalizeGlobalIssues(report),
      priorityFixes: normalizePriorityFixes(report),
    };
  }

  function firstArray(...values) {
    return values.find((value) => Array.isArray(value) && value.length) || [];
  }

  function readEpisodeNumber(item) {
    if (!item || typeof item !== "object") return 0;
    const raw = item.episode ?? item.episode_number ?? item.ep ?? item.index ?? item.episode_or_range ?? item.conflict_location ?? item.where_it_appears ?? item.last_clear_appearance;
    const match = String(raw || "").match(/\d+/);
    return match ? Number(match[0]) : 0;
  }

  function normalizeEpisodeStatus(status, flags = {}) {
    if (flags.missing) return "missing";
    if (flags.duplicate) return "duplicate";
    const text = String(status || "").toLowerCase();
    if (["missing", "empty", "absent"].some((word) => text.includes(word))) return "missing";
    if (["danger", "high", "red", "严重", "缺失"].some((word) => text.includes(word))) return "danger";
    if (flags.shortOrEmpty || ["warning", "flat", "weak", "yellow", "短", "空", "弱"].some((word) => text.includes(word))) return "warning";
    if (["duplicate", "gray", "重复"].some((word) => text.includes(word))) return "duplicate";
    if (["good", "ok", "green", "true", "正常"].some((word) => text.includes(word))) return "good";
    return text ? "warning" : "unknown";
  }

  function normalizeIssues(report, episodeItems) {
    const candidates = [
      ...firstArray(report.episode_map),
      ...firstArray(report.episode_audit),
      ...firstArray(report.episode_rhythm_map),
      ...firstArray(report.weak_hook_episodes),
      ...firstArray(report.relationship_issues),
      ...firstArray(report.motivation_issues),
      ...firstArray(report.causality_issues),
      ...firstArray(report.information_gap_issues),
      ...firstArray(report.rule_consistency),
      ...firstArray(report.emotionally_flat_scenes),
      ...firstArray(report.inner_world_issues),
      ...firstArray(report.resonance_breaks),
      ...firstArray(report.character_appeal_issues),
      ...firstArray(report.opening_hook_rewrites),
      ...firstArray(report.hook_opportunities),
      ...firstArray(report.prose_craft_issues),
      ...firstArray(report.character_entry_hooks),
    ];
    if (!candidates.length && Array.isArray(episodeItems)) {
      candidates.push(...episodeItems.filter((item) => {
        const status = normalizeEpisodeStatus(item.status || item.rhythm_status || item.ending_status || item.hook_status);
        return status !== "good";
      }));
    }
    return candidates.map((item, index) => ({
      title: item.title || item.target || item.issue || item.main_issue || item.current_problem || `第${readEpisodeNumber(item) || index + 1}项问题`,
      severity: item.severity || item.risk || item.status || item.rhythm_status || "warning",
      reason: item.reason || item.why_first || item.current_problem || item.current_ending_problem || item.problem || item.missing_cause || item.why_it_is_wrong || item.issue || "",
      impact: item.impact || item.has_hook || item.has_payoff || item.rhythm_status || item.missing_or_weak_payoff || "",
      fix_direction: item.fix_direction || item.suggested_action || item.better_hook_direction || item.better_payoff_direction || item.rewrite_prompt || "",
      episode: readEpisodeNumber(item),
    })).filter((item) => item.title || item.reason || item.fix_direction);
  }

  function normalizeGlobalIssues(report) {
    const candidates = [
      ...firstArray(report.global_issues, report.issues, report.issue, report.problems),
      ...firstArray(report.payoff_issues).map((item) => ({
        ...item,
        title: item.setup || "爽点兑现不足",
        reason: item.missing_or_weak_payoff,
        impact: "前文承诺没有充分兑现，观众会觉得铺垫落空。",
        fix_direction: item.suggested_payoff,
      })),
      ...firstArray(report.unpaid_setups).map((item) => ({
        ...item,
        title: item.setup || "伏笔未回收",
        reason: item.missing_payoff,
        impact: "重要信息未兑现，会削弱结尾说服力。",
        fix_direction: item.suggested_payoff,
      })),
    ];
    return candidates.map((item, index) => ({
      title: item.title || item.type || item.issue || item.problem || item.target || `核心问题 ${index + 1}`,
      severity: item.severity || item.risk || "medium",
      reason: item.reason || item.problem || item.issue || item.why_first || "",
      impact: item.impact || item.missing_or_weak_payoff || item.missing_payoff || "",
      fix_direction: item.fix_direction || item.suggested_action || item.suggested_payoff || item.rewrite_prompt || "",
      episode: readEpisodeNumber(item),
    })).filter((item) => item.title || item.reason || item.fix_direction);
  }

  function normalizePriorityFixes(report) {
    return firstArray(report.priority_fixes).filter((item) => !isProductionFix(item)).map((item, index) => ({
      rank: item.rank || index + 1,
      target: item.target || item.episode_or_range || item.scope || item.title || `优先修复 ${index + 1}`,
      why_first: item.why_first || item.reason || item.impact || "",
      suggested_action: item.suggested_action || item.fix_direction || item.rewrite_prompt || "",
    })).filter((item) => item.target || item.suggested_action);
  }

  function isProductionFix(item) {
    const text = [
      item && item.target,
      item && item.title,
      item && item.scope,
      item && item.why_first,
      item && item.suggested_action,
      item && item.fix_direction,
    ].filter(Boolean).join(" ");
    return /低成本|可拍|拍摄|拍出来|场景调度|外景|群戏|特效/.test(text);
  }

  function statusLabel(status) {
    return {
      good: "正常",
      warning: "需修",
      danger: "严重",
      missing: "缺失",
      duplicate: "重复",
      unknown: "未知",
    }[status] || "需修";
  }

  function normalizeNumberList(value) {
    if (!Array.isArray(value)) return [];
    return value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
  }

  function renderIssueCard(issue, mode = "global") {
    const episode = Number(issue.episode) || 0;
    const episodeAttr = episode ? ` data-episode-issue="${escapeHtml(episode)}"` : "";
    const title = episode ? `第${episode}集：${issue.title}` : (issue.title || issue.type || "未命名问题");
    return `<article class="wb-issue-card is-${escapeHtml(mode)}"${episodeAttr}>
      <div>
        <strong>${escapeHtml(title)}</strong>
        <span class="wb-issue-severity is-${escapeHtml(String(issue.severity || "normal").toLowerCase())}">${escapeHtml(issue.severity || "normal")}</span>
      </div>
      ${issue.reason ? `<p><b>问题原因：</b>${escapeHtml(issue.reason)}</p>` : ""}
      ${issue.impact ? `<p><b>影响：</b>${escapeHtml(issue.impact)}</p>` : ""}
      ${issue.fix_direction ? `<p><b>修订建议：</b>${escapeHtml(issue.fix_direction)}</p>` : ""}
    </article>`;
  }

  function renderPriorityCard(item) {
    return `<article class="wb-priority-card">
      <span>${escapeHtml(item.rank || "-")}</span>
      <div>
        <strong>${escapeHtml(item.target || "未命名修复项")}</strong>
        ${item.why_first ? `<p><b>为什么先修：</b>${escapeHtml(item.why_first)}</p>` : ""}
        ${item.suggested_action ? `<p><b>操作建议：</b>${escapeHtml(item.suggested_action)}</p>` : ""}
      </div>
    </article>`;
  }

  function bindEpisodeMap(root) {
    $$(".wb-episode-dot", root).forEach((button) => {
      button.addEventListener("click", () => {
        const episode = button.dataset.episode || "";
        const target = $$(".wb-issue-card[data-episode-issue]", root).find((item) => item.dataset.episodeIssue === episode);
        $$(".wb-episode-dot", root).forEach((item) => item.classList.toggle("is-selected", item === button));
        $$(".wb-issue-card", root).forEach((item) => item.classList.remove("is-highlight"));
        if (!target) {
          button.classList.add("is-pulse");
          window.setTimeout(() => button.classList.remove("is-pulse"), 650);
          return;
        }
        target.classList.add("is-highlight");
        const panel = $("#wbEpisodeIssuePanel", root);
        if (panel) panel.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        window.setTimeout(() => target.classList.remove("is-highlight"), 2600);
      });
    });
  }

  async function loadHistory() {
    const list = $("#wbHistoryList");
    if (list) list.innerHTML = '<div class="wb-history-empty">正在读取历史记录...</div>';
    try {
      const data = await fetchJsonWithTimeout("/api/workbuddy/doctor/history?limit=50", 8000);
      currentHistoryItems = Array.isArray(data.items) ? data.items : [];
      renderHistory();
    } catch (error) {
      currentHistoryItems = [];
      if (list) {
        list.innerHTML = `<div class="wb-history-empty">历史记录读取失败：${escapeHtml(error.message || String(error))}</div>`;
      }
    }
  }

  function addHistoryFromResponse(result) {
    if (result && result.history_entry) {
      currentHistoryItems = [result.history_entry, ...currentHistoryItems.filter((item) => item.id !== result.history_entry.id)].slice(0, 50);
      renderHistory();
      return;
    }
    loadHistory();
  }

  function setOptimizationContext(entry, fallbackFilename = "") {
    if (!entry || !entry.id || !entry.can_optimize) {
      currentOptimizationContext = null;
      return;
    }
    currentOptimizationContext = {
      historyEntryId: String(entry.id),
      canOptimize: true,
      filename: String(entry.source_filename || fallbackFilename || uploadedWordSource.filename || "原始剧本.docx"),
    };
  }

  function renderHistory() {
    const list = $("#wbHistoryList");
    const items = currentHistoryItems;
    if (!items.length) {
      list.innerHTML = '<div class="wb-history-empty">暂无历史记录</div>';
      return;
    }
    list.innerHTML = items
      .map((item) => {
        const state = item.ok ? "已完成" : "未完成";
        return `<article class="wb-history-item">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.skill_name || skillNames[item.skill] || item.skill)} · ${state}${item.score ? " · " + escapeHtml(item.score) + "分" : ""}${item.detected_episode_count ? " · " + escapeHtml(item.detected_episode_count) + "集" : ""} · ${escapeHtml(item.created_at_label || item.created_at || "")}</span>
          ${item.message ? `<small>${escapeHtml(item.message)}</small>` : ""}
          <div class="wb-history-actions">
            <button class="wb-mini-btn" type="button" data-history-action="view" data-history-id="${escapeHtml(item.id)}">查看</button>
            <button class="wb-mini-btn" type="button" data-history-action="download" data-history-id="${escapeHtml(item.id)}">下载</button>
            <button class="wb-mini-btn is-danger" type="button" data-history-action="delete" data-history-id="${escapeHtml(item.id)}">删除</button>
          </div>
        </article>`;
      })
      .join("");
  }

  function getHistoryScore(result) {
    const report = parseReportPayload(result);
    return report && report.score != null ? String(report.score) : "";
  }

  async function fetchJsonWithTimeout(url, timeoutMs, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        headers: options.codebuddy ? codebuddyHeaders() : authHeaders(),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || data.message || `请求失败：HTTP ${response.status}`);
      }
      return data;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function deleteJson(url) {
    const response = await fetch(url, { method: "DELETE", headers: authHeaders() });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || data.message || `请求失败：HTTP ${response.status}`);
    }
    return data;
  }

  async function loadStatus() {
    const statusPill = $("#wbStatusPill");
    const configBadge = $("#wbConfigBadge");
    const configText = $("#wbConfigText");
    const accountText = $("#wbAccountText");
    const pointsText = $("#wbPointsText");
    const missingList = $("#wbMissingList");
    statusPill.textContent = "检测配置中";
    statusPill.className = "wb-status-pill is-loading";

    try {
      const fastData = await fetchJsonWithTimeout("/api/workbuddy/status?metadata=0", 6000, { codebuddy: true });
      applyStatusData(fastData, { hydrated: false });
      if (fastData.configured) {
        fetchJsonWithTimeout("/api/workbuddy/status?metadata=1", 12000, { codebuddy: true })
          .then((data) => applyStatusData(data, { hydrated: true }))
          .catch((error) => {
            configText.textContent = "API 已配置；模型列表读取较慢，点击“重新检测”可重试。";
            pointsText.textContent = `积分余额：模型元数据暂未读取（${error.name === "AbortError" ? "请求超时" : error.message || "请求失败"}）`;
            renderModels(cachedModels, activeModel || fastData.model || "");
          });
      }
    } catch (error) {
      statusPill.textContent = "配置检测失败";
      statusPill.className = "wb-status-pill is-missing";
      configBadge.textContent = "失败";
      configBadge.className = "is-missing";
      configText.textContent = "无法读取配置，请确认 5002 服务正在运行。";
      accountText.textContent = "账号：检测失败";
      pointsText.textContent = "积分：检测失败";
      missingList.innerHTML = `<li>${escapeHtml(error.message || String(error))}</li>`;
    }
  }

  function applyStatusData(data, options = {}) {
    const statusPill = $("#wbStatusPill");
    const configBadge = $("#wbConfigBadge");
    const configText = $("#wbConfigText");
    const accountText = $("#wbAccountText");
    const pointsText = $("#wbPointsText");
    const missingList = $("#wbMissingList");

    if (data.configured) {
      statusPill.textContent = options.hydrated ? "DeepSeek 已就绪" : "API 已配置";
      statusPill.className = "wb-status-pill is-ready";
      configBadge.textContent = options.hydrated ? "已配置" : "已连接";
      configBadge.className = "is-ready";
      configText.textContent = options.hydrated
        ? `SDK 已安装，API Key 已设置，中国区 internal 环境已启用。默认使用 Auto 自动选择，可手动指定模型。当前 CLI 模型：${data.model || "平台默认"}。`
        : "API Key 与 internal 环境已检测通过，正在读取模型列表。";
      accountText.textContent = Object.keys(data.account || {}).length ? formatAccount(data.account || {}) : "账号：已连接，正在读取账号信息";
      pointsText.textContent = options.hydrated ? formatPoints(data) : "积分余额：正在读取余额信息";
      missingList.innerHTML = "";
      const models = Array.isArray(data.models) && data.models.length ? data.models : cachedModels;
      renderModels(models, data.model || activeModel || "");
    } else {
      statusPill.textContent = "DeepSeek 未配置";
      statusPill.className = "wb-status-pill is-missing";
      configBadge.textContent = "缺配置";
      configBadge.className = "is-missing";
      configText.textContent = "剧本医生页面已可用，但真实 WorkBuddy 智能体调用还缺以下配置：";
      accountText.textContent = "账号：未连接";
      pointsText.textContent = "积分余额：未连接";
      missingList.innerHTML = (data.missing || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
      renderModels(data.models || [], data.model || "");
    }
  }

  function formatAccount(account) {
    const name = account.nickname || account.user_name || account.user_id || "已连接账号";
    const detail = [account.type, account.enterprise].filter(Boolean).join(" · ");
    return detail ? `账号：${name} · ${detail}` : `账号：${name}`;
  }

  function formatPoints(data) {
    if (data.points_supported) {
      return `积分余额：${data.points}`;
    }
    if (data.metadata_error) {
      return `积分余额：暂未读取（${data.metadata_error}）`;
    }
    return "用量由平台统一的 DeepSeek V4 Pro API 账户结算。";
  }

  function renderModels(models, currentModel) {
    const box = $("#wbModelOptions");
    const hint = $("#wbModelHint");
    const input = $("#wbModelInput");
    const toggle = $("#wbToggleModelsBtn");
    const normalized = withAutoModel(prioritizeModels(Array.isArray(models) ? models.filter((item) => item && item.id) : [], currentModel));
    cachedModels = normalized;
    cachedDefaultModel = currentModel || "";
    if (!normalized.length) {
      activeModel = activeModel || "auto";
      input.value = modelValueForSubmit(activeModel);
      box.innerHTML = activeModel
        ? `<button class="wb-model-chip is-active" type="button" data-model="${escapeHtml(activeModel)}">${escapeHtml(activeModel)}</button>`
        : '<span class="wb-model-empty">暂无可用模型列表</span>';
      hint.textContent = activeModel ? "自动选择模型。" : "未读取到模型。";
      if (toggle) toggle.hidden = true;
      return;
    }

    const ids = new Set(normalized.map((item) => item.id));
    activeModel = ids.has(activeModel) ? activeModel : "auto";
    input.value = modelValueForSubmit(activeModel);
    const visibleModels = getVisibleModels(normalized, activeModel);
    const hiddenCount = Math.max(0, normalized.length - visibleModels.length);
    hint.textContent = modelPickerExpanded || !hiddenCount
      ? `本次调用使用：${activeModel}`
      : `本次调用使用：${activeModel} · 还有 ${hiddenCount} 个模型`;
    if (toggle) {
      toggle.hidden = normalized.length <= 3;
      toggle.textContent = modelPickerExpanded ? "收起" : `展开全部 ${normalized.length}`;
    }
    box.classList.toggle("is-expanded", modelPickerExpanded);
    box.innerHTML = visibleModels
      .map((item) => {
        const active = item.id === activeModel ? " is-active" : "";
        return `<button class="wb-model-chip${active}" type="button" data-model="${escapeHtml(item.id)}" title="${escapeHtml(item.description || item.id)}">
          <strong>${escapeHtml(item.name || item.id)}</strong>
          <span>${escapeHtml(item.id)}</span>
        </button>`;
      })
      .join("");
    $$(".wb-model-chip", box).forEach((button) => {
      button.addEventListener("click", () => {
        activeModel = button.dataset.model || "";
        input.value = modelValueForSubmit(activeModel);
        hint.textContent = `本次调用使用：${activeModel}`;
        $$(".wb-model-chip", box).forEach((item) => item.classList.toggle("is-active", item === button));
      });
    });
  }

  function withAutoModel(models) {
    return [
      {
        id: "auto",
        name: "Auto 自动选择",
        description: "使用平台统一配置的 DeepSeek V4 Pro 模型。",
      },
      ...models.filter((item) => item.id !== "auto"),
    ];
  }

  function modelValueForSubmit(modelId) {
    return modelId === "auto" ? "" : modelId;
  }

  function prioritizeModels(models, currentModel) {
    const preferred = [
      "auto",
      "glm-5.2",
      "deepseek-v4-flash",
      "glm-5.1",
      "deepseek-v4-pro",
      "kimi-k2.7",
    ].filter(Boolean);
    return [...models].sort((a, b) => {
      const ai = preferred.indexOf(a.id);
      const bi = preferred.indexOf(b.id);
      if (ai !== -1 || bi !== -1) {
        return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
      }
      return String(a.name || a.id).localeCompare(String(b.name || b.id), "zh-CN");
    });
  }

  function getVisibleModels(models, selectedId) {
    if (modelPickerExpanded || models.length <= 3) return models;
    const visible = models.slice(0, 3);
    if (selectedId && !visible.some((item) => item.id === selectedId)) {
      visible[2] = models.find((item) => item.id === selectedId) || visible[2];
    }
    return visible;
  }

  function setupSkills() {
    $$(".wb-skill-card").forEach((button) => {
      button.addEventListener("click", () => {
        activeSkill = button.dataset.skill || "overall_dispatcher";
        $$(".wb-skill-card").forEach((item) => item.classList.toggle("is-active", item === button));
        $("#wbCurrentSkill").textContent = skillNames[activeSkill] || "总质检调度器";
        updateGoalOptions(activeSkill);
      });
    });
    updateGoalOptions(activeSkill);
  }

  function updateGoalOptions(skillKey) {
    const select = $("#wbGoalSelect");
    const hint = $("#wbGoalHint");
    const config = skillGoalOptions[skillKey] || skillGoalOptions.overall_dispatcher;
    if (!select || !config) return;
    const current = select.value;
    select.innerHTML = config.options
      .map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`)
      .join("");
    if (config.options.includes(current)) {
      select.value = current;
    } else {
      select.value = config.options[0] || "";
    }
    if (hint) hint.textContent = config.hint || "";
  }

  function getScriptStats(text) {
    const length = (text || "").trim().length;
    const episodeMatches = (text || "").match(/第\s*[0-9一二三四五六七八九十百]+\s*[集章回]/g) || [];
    const uniqueEpisodes = new Set(episodeMatches.map((item) => item.replace(/\s+/g, "")));
    return { length, episodes: uniqueEpisodes.size };
  }

  function updateStats() {
    const textarea = $('#wbDoctorForm textarea[name="script_text"]');
    const stats = getScriptStats(textarea.value);
    const text = stats.length
      ? `已输入 ${stats.length} 字，识别到约 ${stats.episodes || 0} 集`
      : "尚未输入剧本";
    $("#wbScriptStats").textContent = text;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...codebuddyHeaders(),
      },
      body: JSON.stringify(payload),
    });
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      data = { ok: false, error: text || response.statusText };
    }
    if (!response.ok && !data.error) {
      data.error = `请求失败：HTTP ${response.status}`;
    }
    return data;
  }

  function setupFileImport() {
    const input = $("#wbScriptFile");
    const textarea = $('#wbDoctorForm textarea[name="script_text"]');
    const titleInput = $('#wbDoctorForm input[name="title"]');
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      if (!/\.(txt|docx|pdf)$/i.test(file.name)) {
        setResult({ ok: false, error: "当前只支持上传 TXT、Word DOCX、PDF 文件。" });
        input.value = "";
        return;
      }
      setResult({ ok: true, message: `正在解析文件：${file.name}` });
      currentOptimizationContext = null;
      const formData = new FormData();
      formData.append("file", file);
      try {
        const isWord = /\.docx$/i.test(file.name);
        const response = await fetch(isWord ? "/api/workbuddy/doctor/source" : "/api/files/extract-text", {
          method: "POST",
          headers: authHeaders(),
          body: formData,
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
          throw new Error(data.message || data.error || `文件解析失败：HTTP ${response.status}`);
        }
        textarea.value = data.text || "";
        uploadedWordSource = isWord && data.source_document_id
          ? {
              id: String(data.source_document_id),
              filename: String(data.filename || file.name),
              scriptSnapshot: textarea.value,
            }
          : { id: "", filename: "", scriptSnapshot: "" };
        if (!titleInput.value.trim()) titleInput.value = (data.filename || file.name).replace(/\.[^.]+$/, "");
        updateStats();
        setResult({
          ok: true,
          message: "文件解析完成，正文已填入输入框。",
          filename: data.filename || file.name,
          char_count: data.char_count || textarea.value.length,
          one_click_optimization: uploadedWordSource.id ? "审查完成后可一键优化并下载 Word" : "当前文件仅支持文本审查",
        });
      } catch (error) {
        setResult({ ok: false, error: error.message || String(error) });
      } finally {
        input.value = "";
      }
    });
  }

  function setupForm() {
    const form = $("#wbDoctorForm");
    const textarea = $('textarea[name="script_text"]', form);
    textarea.addEventListener("input", updateStats);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $(".wb-primary-btn", form);
      const formData = Object.fromEntries(new FormData(form).entries());
      const payload = {
        title: formData.title || "",
        user_goal: formData.user_goal || "",
        script_text: formData.script_text || "",
        skill: activeSkill,
        model: formData.model || modelValueForSubmit(activeModel) || "",
        source_document_id: uploadedWordSource.id && textarea.value === uploadedWordSource.scriptSnapshot
          ? uploadedWordSource.id
          : "",
      };
      const original = button.textContent;
      button.disabled = true;
      form.classList.add("is-running");
      button.textContent = "AI 正在体检";
      setRunningResult(payload);
      try {
        const data = await postJson("/api/workbuddy/doctor/run", payload);
        setOptimizationContext(data && data.history_entry, uploadedWordSource.filename);
        if (data && data.ok && data.report) {
          setResult({
            report: data.report,
            structured_output: data.structured_output,
            usage: data.usage,
            model: data.model,
            session_id: data.session_id,
          });
        } else {
          setResult(data);
        }
        addHistoryFromResponse(data);
      } catch (error) {
        setResult({ ok: false, error: error.message || String(error) });
      } finally {
        button.disabled = false;
        button.textContent = original;
        form.classList.remove("is-running");
        clearRunningTimer();
      }
    });

    $("#wbClearFormBtn").addEventListener("click", () => {
      form.reset();
      uploadedWordSource = { id: "", filename: "", scriptSnapshot: "" };
      currentOptimizationContext = null;
      updateStats();
      setResult("等待上传剧本并运行体检。");
    });
  }

  function setupApiConfigDialog() {
    const dialog = $("#wbApiConfigDialog");
    const openButton = $("#wbOpenApiConfigBtn");
    const closeButton = $("#wbApiConfigCloseBtn");
    const saveButton = $("#wbApiConfigSaveBtn");
    const clearButton = $("#wbApiConfigClearBtn");
    const apiKeyInput = $("#wbApiKeyInput");
    const envInput = $("#wbApiEnvInput");
    const hint = $("#wbApiConfigHint");

    function syncInputs() {
      const apiConfig = readApiConfig();
      apiKeyInput.value = apiConfig.apiKey || "";
      envInput.value = apiConfig.internetEnvironment || "internal";
      hint.textContent = apiConfig.apiKey
        ? "当前浏览器已保存 API Key。可以直接检测，也可以粘贴新的 Key 覆盖。"
        : "粘贴 API Key 后点击“保存并检测”。后续可在这里更换会员账号 Key。";
    }

    function openDialog() {
      syncInputs();
      dialog.hidden = false;
      document.body.classList.add("wb-dialog-open");
      window.setTimeout(() => apiKeyInput.focus(), 0);
    }

    function closeDialog() {
      dialog.hidden = true;
      document.body.classList.remove("wb-dialog-open");
    }

    openButton.addEventListener("click", openDialog);
    closeButton.addEventListener("click", closeDialog);
    $$("[data-api-dialog-close]", dialog).forEach((item) => item.addEventListener("click", closeDialog));
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDialog();
    });
    saveButton.addEventListener("click", async () => {
      const apiKey = apiKeyInput.value.trim();
      if (!apiKey) {
        hint.textContent = "DeepSeek API Key 已由平台统一配置，无需在浏览器填写。";
        apiKeyInput.focus();
        return;
      }
      saveApiConfig({
        apiKey,
        internetEnvironment: envInput.value || "internal",
      });
      hint.textContent = "已保存到当前浏览器，正在检测连接。";
      await loadStatus();
      closeDialog();
    });
    clearButton.addEventListener("click", async () => {
      clearApiConfig();
      apiKeyInput.value = "";
      envInput.value = "internal";
      hint.textContent = "已清除当前浏览器保存的 API Key。";
      await loadStatus();
    });
  }

  function setupActions() {
    $("#wbRefreshStatusBtn").addEventListener("click", loadStatus);
    $("#wbToggleModelsBtn").addEventListener("click", () => {
      modelPickerExpanded = !modelPickerExpanded;
      renderModels(cachedModels, cachedDefaultModel);
    });
    $("#wbClearHistoryBtn").addEventListener("click", async () => {
      if (!window.confirm("确定清空全部剧本医生历史记录吗？")) return;
      try {
        await deleteJson("/api/workbuddy/doctor/history");
        currentHistoryItems = [];
        currentOptimizationContext = null;
        renderHistory();
      } catch (error) {
        setResult({ ok: false, error: error.message || String(error) });
      }
    });
    $("#wbHistoryList").addEventListener("click", async (event) => {
      const button = event.target.closest("[data-history-action]");
      if (!button) return;
      const entryId = button.dataset.historyId || "";
      const action = button.dataset.historyAction || "";
      if (!entryId) return;
      try {
        if (action === "delete") {
          if (!window.confirm("确定删除这条历史记录吗？")) return;
          const data = await deleteJson(`/api/workbuddy/doctor/history/${encodeURIComponent(entryId)}`);
          currentHistoryItems = Array.isArray(data.items) ? data.items : currentHistoryItems.filter((item) => item.id !== entryId);
          renderHistory();
          if (currentOptimizationContext && currentOptimizationContext.historyEntryId === entryId) {
            currentOptimizationContext = null;
          }
          return;
        }
        const data = await fetchJsonWithTimeout(`/api/workbuddy/doctor/history/${encodeURIComponent(entryId)}`, 8000);
        const entry = data.entry || {};
        const result = entry.result || {};
        setOptimizationContext({
          id: entry.id,
          can_optimize: Boolean(entry.ok && entry.source_document_id),
          source_filename: entry.source_filename || "原始剧本.docx",
        });
        setResult(result.report || result.structured_output ? {
          report: result.report,
          structured_output: result.structured_output,
          usage: result.usage,
          model: result.model,
          session_id: result.session_id,
        } : result);
        if (action === "download") {
          downloadText(
            `AI剧本医生报告-${entry.title || "未命名剧本"}-${String(entry.created_at_label || "").replace(/[\\/:*?"<>|\s]+/g, "-")}.json`,
            JSON.stringify(entry, null, 2)
          );
        }
      } catch (error) {
        setResult({ ok: false, error: error.message || String(error) });
      }
    });
    $("#wbCopyResultBtn").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText($("#wbResultBox").textContent || "");
      } catch (error) {
        setResult({ ok: false, error: "复制失败，请手动选择报告文本。" });
      }
    });
    $("#wbDownloadResultBtn").addEventListener("click", () => {
      downloadText(`AI剧本医生报告-${new Date().toISOString().slice(0, 10)}.txt`, $("#wbResultBox").textContent || "");
    });
    $("#wbReportView").addEventListener("click", async (event) => {
      const button = event.target.closest('[data-report-action="optimize"]');
      if (!button || !currentOptimizationContext) return;
      const status = $("#wbOptimizeStatus");
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "AI 正在逐段优化";
      if (status) status.textContent = "正在依据审查报告生成修改，并核对 Word 原段落。长剧本可能需要数分钟。";
      try {
        const data = await postJson(
          `/api/workbuddy/doctor/history/${encodeURIComponent(currentOptimizationContext.historyEntryId)}/optimize`,
          { model: modelValueForSubmit(activeModel) || "" }
        );
        if (!data || data.ok === false || !data.download_url) {
          throw new Error((data && (data.error || data.message)) || "一键优化失败。");
        }
        if (status) {
          status.textContent = `已安全回写 ${data.applied_count || 0} 个段落${data.skipped_count ? `，跳过 ${data.skipped_count} 个未通过校验的修改` : ""}，正在下载。`;
        }
        await downloadAuthenticated(data.download_url, data.download_name || "AI优化版剧本.docx");
      } catch (error) {
        if (status) status.textContent = error.message || String(error);
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
  }

  async function downloadAuthenticated(url, filename) {
    const response = await fetch(url, { headers: authHeaders() });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || data.message || `下载失败：HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  function downloadText(filename, content) {
    const blob = new Blob([content || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupSkills();
    setupFileImport();
    setupForm();
    setupApiConfigDialog();
    setupActions();
    loadHistory();
    updateStats();
    loadStatus();
  });
})();
