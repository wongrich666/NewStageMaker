(() => {
  const config = window.COMPLIANCE_REVIEW_CONFIG || {};
  const root = document.getElementById("compliance-review-app");
  const state = {
    view: "compliance",
    catalog: null,
    mode: "standard",
    region: "国家/全国",
    platforms: new Set(["douyin", "hongguo", "bilibili"]),
    text: "",
    filename: "",
    useAi: false,
    loading: false,
    report: null,
    history: [],
    ratingHistory: [],
    selectedFixes: new Set(),
    repairLoading: false,
    repair: null,
    repairDirection: "",
    error: "",
  };

  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const apiUrl = (path) => {
    const url = new URL(path, window.location.origin);
    if (config.authToken) url.searchParams.set("auth_token", config.authToken);
    return url.toString();
  };

  async function api(path, options = {}) {
    const response = await fetch(apiUrl(path), {
      credentials: "same-origin",
      ...options,
      headers: options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || data.message || `请求失败（HTTP ${response.status}）`);
    }
    return data;
  }

  function icon(name, size = 18) {
    return `<i data-lucide="${name}" style="width:${size}px;height:${size}px" aria-hidden="true"></i>`;
  }

  function modeDescription() {
    if (state.view === "rating") {
      return state.mode === "advanced"
        ? "逐集深读钩子兑现、主线因果、连续性与情绪曲线，适合送审、签约或重点制作前评估。"
        : "快速完成八维质量预评级，适合初稿筛选和确定优先修改项。";
    }
    if (state.mode === "advanced") {
      return "适用于100万元以上、特殊题材、平台主推或首页首推项目；增加备案材料、属地复核与上下文审查。";
    }
    return "适用于一般项目的创作前自查，先跑国家底线和所选平台高风险规则。";
  }

  function selectedPlatformNames() {
    return (state.catalog?.platforms || [])
      .filter((item) => state.platforms.has(item.id))
      .map((item) => item.name);
  }

  function complianceResultMarkup() {
    if (state.loading) {
      return `<section class="cr-result-empty cr-loading">
        <span class="cr-spinner"></span>
        <strong>${state.useAi ? "规则引擎与AI正在联合复核" : "规则引擎正在逐行检测"}</strong>
        <p>正在定位风险原句并生成保留戏剧功能的修改建议。</p>
      </section>`;
    }
    if (state.error) {
      return `<section class="cr-result-empty cr-error">
        ${icon("circle-alert", 28)}
        <strong>检测没有完成</strong>
        <p>${esc(state.error)}</p>
      </section>`;
    }
    if (!state.report) {
      return `<section class="cr-result-empty">
        <div class="cr-empty-icon">${icon("scan-search", 30)}</div>
        <strong>等待检测</strong>
        <p>结果会按风险等级排列，并标出原句、依据和可执行修改方向。</p>
      </section>`;
    }

    const report = state.report;
    const count = report.counts || {};
    const scoreClass = report.status === "blocked" || report.status === "revision_required"
      ? "is-danger"
      : report.status === "review_recommended" ? "is-warning" : "is-safe";
    const findings = (report.findings || []).map((item) => `
      <article class="cr-finding cr-severity-${esc(item.severity)}">
        <div class="cr-finding-head">
          <span class="cr-severity">${severityName(item.severity)}</span>
          <span class="cr-origin">${item.origin === "ai" ? "AI上下文复核" : `规则定位${item.line ? ` · 第${item.line}行` : ""}`}</span>
        </div>
        <h3>${esc(item.title)}</h3>
        ${item.excerpt ? `<blockquote>${esc(item.excerpt)}</blockquote>` : ""}
        <dl>
          <div><dt>为什么需要改</dt><dd>${esc(item.reason)}</dd></div>
          <div><dt>建议怎么改</dt><dd>${esc(item.suggestion)}</dd></div>
        </dl>
        <div class="cr-basis-row">${(item.basis_ids || []).map((id) => `<span>${esc(id)}</span>`).join("")}</div>
      </article>`).join("");
    const checklist = (report.checklist || []).map((item) => `
      <li>${icon("square-check-big", 16)}<span><strong>${esc(item.title)}</strong>${esc(item.detail)}</span></li>`).join("");
    const aiNotice = report.ai?.enabled
      ? report.ai.ok
        ? `<span class="cr-ai-ok">${icon("sparkles", 15)} AI复核完成${report.ai.truncated ? "（超长文本仅复核前段，规则检测仍覆盖全文）" : ""}</span>`
        : `<span class="cr-ai-failed">AI复核未完成：${esc(report.ai.error || "上游不可用")}；规则检测结果仍有效。</span>`
      : "";
    const escalation = report.advanced_mode?.recommended
      ? `<div class="cr-escalation">${icon("shield-alert", 18)}<span><strong>建议升级高级检测</strong>${esc(report.advanced_mode.message)}<small>触发原因：${(report.advanced_mode.reasons || []).map(esc).join("、")}</small></span><button type="button" id="crUpgrade">切换高级检测</button></div>`
      : "";

    return `<section class="cr-report">
      <div class="cr-report-summary">
        <div class="cr-score ${scoreClass}" style="--score:${Number(report.risk_score || 0)}">
          <strong>${Number(report.risk_score || 0)}</strong><span>风险值</span>
        </div>
        <div class="cr-summary-copy">
          <span class="cr-kicker">检测结论</span>
          <h2>${esc(report.conclusion)}</h2>
          <p>共检查 ${Number(report.metrics?.characters || 0).toLocaleString()} 字符、${report.metrics?.episodes || 0} 集标记。风险值越高越需优先修改；0只代表规则库未明确命中，不代表过审。</p>
          ${aiNotice}
        </div>
      </div>
      <div class="cr-counts" aria-label="风险统计">
        <div><strong>${count.critical || 0}</strong><span>紧急</span></div>
        <div><strong>${count.high || 0}</strong><span>高风险</span></div>
        <div><strong>${count.medium || 0}</strong><span>中风险</span></div>
        <div><strong>${count.low || 0}</strong><span>提示</span></div>
      </div>
      ${escalation}
      ${checklist ? `<section class="cr-checklist"><h3>高级项目送审准备</h3><ul>${checklist}</ul></section>` : ""}
      <div class="cr-findings-head"><h3>逐条修改建议</h3><span>${report.findings?.length || 0} 条</span></div>
      <div class="cr-findings">${findings || `<div class="cr-pass-state">${icon("badge-check", 24)}<strong>未发现明确规则命中</strong><p>仍需结合成片画面、声音、字幕、宣传文案和平台当日规则进行人工终审。</p></div>`}</div>
    </section>`;
  }

  function ratingResultMarkup() {
    if (state.loading) return `<section class="cr-result-empty cr-loading"><span class="cr-spinner"></span><strong>AI正在逐集阅读与交叉评分</strong><p>正在核对主线、钩子兑现、冲突升级、连续性和可制作性。</p></section>`;
    if (state.error) return `<section class="cr-result-empty cr-error">${icon("circle-alert", 28)}<strong>评级没有完成</strong><p>${esc(state.error)}</p></section>`;
    if (!state.report) return `<section class="cr-result-empty"><div class="cr-empty-icon">${icon("chart-no-axes-combined", 30)}</div><strong>等待评级</strong><p>AI会给出八维评分、原文证据和按优先级排列的重写建议。</p></section>`;
    const report = state.report;
    const dimensions = (report.dimensions || []).map((item, dimensionIndex) => `<article class="cr-dimension">
      <div class="cr-dimension-head"><span><strong>${esc(item.name)}</strong><small>权重 ${item.weight}%</small></span><b>${Number(item.score || 0)}</b></div>
      <div class="cr-meter"><i style="width:${Math.max(0, Math.min(100, Number(item.score || 0)))}%"></i></div>
      <p>${esc(item.verdict)}</p>
      ${(item.evidence || []).length ? `<blockquote>${esc(item.evidence[0])}</blockquote>` : ""}
      ${(item.actions || []).length ? `<div class="cr-dimension-actions"><small>可选修改建议</small>${item.actions.slice(0, 2).map((value, actionIndex) => {
        const key = `dimension:${item.id || dimensionIndex}:${actionIndex}`;
        return `<label class="cr-dimension-action ${state.selectedFixes.has(key) ? "is-selected" : ""}"><input type="checkbox" data-repair-key="${esc(key)}" ${state.selectedFixes.has(key) ? "checked" : ""} /><span>${esc(value)}</span></label>`;
      }).join("")}</div>` : ""}
    </article>`).join("");
    const fixes = (report.priority_fixes || []).map((item, index) => {
      const key = `priority:${index}`;
      return `<article class="cr-priority-fix ${state.selectedFixes.has(key) ? "is-selected" : ""}"><label><input type="checkbox" data-repair-key="${key}" ${state.selectedFixes.has(key) ? "checked" : ""} /><span>${Number(item.priority || index + 1)}</span></label><div><strong>${esc(item.title)}</strong><small>${esc(item.location || "全剧")}</small><p>${esc(item.action)}</p><em>${esc(item.expected_gain || "")}</em></div></article>`;
    }).join("");
    const allRepairKeys = repairIssueKeys(report);
    const gate = report.compliance_gate || {};
    return `<section class="cr-report cr-rating-report">
      <div class="cr-rating-hero"><div class="cr-grade"><strong>${esc(report.grade)}</strong><span>${Number(report.score || 0)}分</span></div><div><span class="cr-kicker">平台自研质量预评级</span><h2>${esc(report.grade_label)}</h2><p>${esc(report.one_line_verdict)}</p></div></div>
      <div class="cr-rating-note">${icon("info", 15)}${esc(report.methodology?.note || "该结果不是平台官方评级。")}</div>
      ${gate.status !== "clear" ? `<div class="cr-rating-gate">${icon("shield-alert", 18)}合规门槛限制：质量原始分 ${Number(report.raw_quality_score || 0)}，因“${esc(gate.conclusion)}”最终评级上限为 ${Number(gate.score_cap || 0)} 分。</div>` : ""}
      <section class="cr-rating-brief"><div><span>观众承诺</span><p>${esc(report.audience_promise || "未识别")}</p></div><div><span>主线复述</span><p>${esc(report.mainline_summary || "主线尚不清晰")}</p></div></section>
      <div class="cr-findings-head"><h3>八维评分</h3><span>总权重 100%</span></div><div class="cr-dimension-grid">${dimensions}</div>
      <div class="cr-findings-head"><h3>优先修改</h3><span>${report.priority_fixes?.length || 0} 项</span></div><div class="cr-priority-list">${fixes || `<div class="cr-pass-state"><strong>暂无明确修改项</strong></div>`}</div>
      ${allRepairKeys.length ? `<section class="cr-repair-box">
        <div class="cr-repair-head"><div>${icon("wand-sparkles", 19)}<span><strong>AI精准修复</strong><small>八维建议与优先问题均可勾选，只替换精确命中的原文片段</small></span></div><button type="button" id="crSelectAllFixes">${state.selectedFixes.size === allRepairKeys.length ? "取消全选" : "全选全部建议"}</button></div>
        <div class="cr-repair-selection">已选择 <strong>${state.selectedFixes.size}</strong> / ${allRepairKeys.length} 项</div>
        <textarea id="crRepairDirection" maxlength="1200" placeholder="可选：补充你希望保留或强化的方向">${esc(state.repairDirection)}</textarea>
        <button type="button" class="cr-repair-run" id="crRepairRun" ${state.repairLoading || !state.selectedFixes.size ? "disabled" : ""}>${state.repairLoading ? `<span class="cr-button-spinner"></span>正在精准定位并修复` : `${icon("wand-sparkles", 17)}修复所选问题`}</button>
        ${repairMarkup()}
      </section>` : ""}
      <section class="cr-audit-pair"><div><h3>钩子链</h3><p>${esc(report.hook_audit?.opening || "未给出")}</p><p>${esc(report.hook_audit?.episode_chain || "未给出")}</p></div><div><h3>连续性</h3><p>${esc(report.continuity_audit?.status || "未判断")}</p><p>${esc((report.continuity_audit?.problems || []).join("；") || "未发现明确断点")}</p></div></section>
    </section>`;
  }

  function repairMarkup() {
    if (!state.repair) return "";
    const patches = (state.repair.applied_patches || []).map((item) => `<article class="cr-repair-patch"><div><strong>${esc(item.location || "精准片段")}</strong><span>${esc(item.reason)}</span></div><details><summary>查看修改前后</summary><section><label>修改前</label><pre>${esc(item.original_exact)}</pre><label>修改后</label><pre>${esc(item.replacement)}</pre></section></details></article>`).join("");
    return `<div class="cr-repair-result"><div class="cr-repair-result-head"><span>${icon("badge-check", 18)}<strong>${esc(state.repair.summary)}</strong><small>已精确应用 ${state.repair.applied_patches?.length || 0} 处，未覆盖左侧原文</small></span><button type="button" id="crApplyRepair">应用到左侧文本</button></div>${patches}</div>`;
  }

  function repairIssueKeys(report) {
    const keys = (report?.priority_fixes || []).map((_, index) => `priority:${index}`);
    (report?.dimensions || []).forEach((item, dimensionIndex) => {
      (item.actions || []).slice(0, 2).forEach((_, actionIndex) => keys.push(`dimension:${item.id || dimensionIndex}:${actionIndex}`));
    });
    return keys;
  }

  function resultMarkup() {
    return state.view === "rating" ? ratingResultMarkup() : complianceResultMarkup();
  }

  function severityName(value) {
    return ({ critical: "紧急", high: "高风险", medium: "中风险", low: "提示" })[value] || "复核";
  }

  function sourceMarkup() {
    if (!state.catalog) return "";
    return `<details class="cr-sources">
      <summary><span>${icon("library", 18)}规则资料库</span><span>${state.catalog.sources.length} 个官方入口 ${icon("chevron-down", 16)}</span></summary>
      <div class="cr-source-grid">
        ${state.catalog.sources.map((source) => `<a href="${esc(source.url)}" target="_blank" rel="noreferrer" class="cr-source-item">
          <span>${esc(source.scope)} · ${esc(source.authority)}</span>
          <strong>${esc(source.title)}</strong>
          <p>${esc(source.summary)}</p>
          <small>${esc(source.status)}${source.published ? ` · ${esc(source.published)}` : ""}</small>
        </a>`).join("")}
      </div>
      <p class="cr-source-note">当前是截至 ${esc(state.catalog.verified_at || "最近核验日")} 的人工核验规则索引，不是自动抓取全量法规库。省级文件通过国家广电总局“地方管理机构”目录进入属地官网复核；平台规则会动态调整，发布前仍应核对创作者后台当日版本。</p>
    </details>`;
  }

  function historyMarkup() {
    const records = state.view === "rating" ? state.ratingHistory : state.history;
    const isRating = state.view === "rating";
    return `<section class="cr-history" id="crHistory">
      <div class="cr-history-head">
        <div><span>${icon("history", 18)}</span><h2>${isRating ? "评级记录" : "检测记录"}</h2><small>每次完成后自动保存</small></div>
        ${records.length ? `<button type="button" id="crClearHistory" title="清空检测记录">${icon("trash-2", 15)}清空</button>` : ""}
      </div>
      <div class="cr-history-list">
        ${records.length ? records.map((record) => {
          const report = record.report || {};
          return `<article class="cr-history-item">
            <button type="button" class="cr-history-open" data-history-open="${esc(record.id)}">
              <span class="cr-history-risk ${isRating ? "rating" : esc(report.status || "not_detected")}">${isRating ? esc(report.grade || "-") : Number(report.risk_score || 0)}</span>
              <span><strong>${esc(record.title)}</strong><small>${record.level === "advanced" || record.mode === "advanced" ? "深度" : "快速"}${isRating ? "评级" : "检测"} · ${Number(record.script_chars || 0).toLocaleString()}字符 · ${esc(new Date(record.created_at).toLocaleString("zh-CN", { hour12: false }))}</small></span>
              <em>${esc(isRating ? `${report.score || 0}分 · ${report.grade_label || "查看报告"}` : report.conclusion || "查看报告")}</em>
            </button>
            <button type="button" class="cr-history-delete" data-history-delete="${esc(record.id)}" title="删除这条记录">${icon("trash-2", 15)}</button>
          </article>`;
        }).join("") : `<div class="cr-history-empty">${icon("inbox", 20)}暂无${isRating ? "评级" : "检测"}记录。</div>`}
      </div>
    </section>`;
  }

  function render() {
    const catalog = state.catalog || { regions: ["国家/全国"], platforms: [], ai: {} };
    root.innerHTML = `
      <header class="cr-topbar">
        <a class="cr-brand" href="${esc(config.workspaceUrl || "/workspace")}">
          <span class="cr-brand-icon">${icon("shield-check", 22)}</span>
          <span><strong>合规检测 / 评级打分</strong><small>风险准入与剧本质量分开判断</small></span>
        </a>
        <div class="cr-top-actions">
          <a class="cr-history-jump" href="#crHistory">${icon("history", 16)}${state.view === "rating" ? "评级" : "检测"}记录${(state.view === "rating" ? state.ratingHistory.length : state.history.length) ? ` ${state.view === "rating" ? state.ratingHistory.length : state.history.length}` : ""}</a>
          <a class="cr-back" href="${esc(config.workspaceUrl || "/workspace")}">${icon("arrow-left", 17)}返回工作台</a>
        </div>
      </header>
      <div class="cr-page">
        <nav class="cr-section-tabs" aria-label="功能页面">
          <button type="button" data-view="compliance" class="${state.view === "compliance" ? "is-active" : ""}">${icon("shield-check", 18)}<span><strong>合规检测</strong><small>法规、属地与平台风险</small></span></button>
          <button type="button" data-view="rating" class="${state.view === "rating" ? "is-active" : ""}">${icon("chart-no-axes-combined", 18)}<span><strong>评级打分</strong><small>主线、钩子、情绪与商业质量</small></span></button>
        </nav>
        <section class="cr-intro">
          <div><span class="cr-eyebrow">${state.view === "rating" ? "SCRIPT QUALITY RATING" : "SCRIPT COMPLIANCE"}</span><h1>${state.view === "rating" ? "不是有没有写，而是写得够不够好。" : "先把风险找出来，再保住戏。"}</h1><p>${state.view === "rating" ? "八维预评级，逐项给原文证据与最值得先改的地方。" : "定位剧本原句、解释风险来源，并给出不牺牲冲突与人物弧线的修改方向。"}</p></div>
          <div class="cr-source-status">${icon(state.view === "rating" ? "badge" : "database", 19)}<span><strong>${state.view === "rating" ? "S+ 至 C 六档" : `${catalog.sources?.length || 0} 个已核验入口`}</strong><small>${state.view === "rating" ? "自研预评级，不冒充平台官方" : "国家规则、属地目录与主要平台"}</small></span></div>
        </section>

        <div class="cr-workspace">
          <section class="cr-editor-panel">
            <div class="cr-panel-heading"><div><span>01</span><h2>${state.view === "rating" ? "评级范围" : "检测范围"}</h2></div><small>选择项目实际市场与发布环境</small></div>
            <div class="cr-mode-switch" role="group" aria-label="检测等级">
              <button type="button" data-mode="standard" class="${state.mode === "standard" ? "is-active" : ""}">${icon("scan-line", 18)}<span><strong>${state.view === "rating" ? "快速评级" : "普通检测"}</strong><small>${state.view === "rating" ? "初稿筛选 · 八维判断" : "一般项目 · 快速预检"}</small></span></button>
              <button type="button" data-mode="advanced" class="${state.mode === "advanced" ? "is-active" : ""}">${icon("shield-alert", 18)}<span><strong>${state.view === "rating" ? "深度评级" : "高级检测"}</strong><small>${state.view === "rating" ? "逐集深读 · 重点项目" : "100万以上 / 重点项目"}</small></span></button>
            </div>
            <p class="cr-mode-help">${esc(modeDescription())}</p>
            <div class="cr-fields">
              <label><span>${state.view === "rating" ? "目标市场" : "申报地区"}</span><select id="crRegion">${catalog.regions.map((item) => `<option value="${esc(item)}" ${item === state.region ? "selected" : ""}>${esc(item)}</option>`).join("")}</select></label>
              <div class="cr-platform-field"><span>目标平台</span><div class="cr-platforms">${catalog.platforms.map((item) => `<button type="button" data-platform="${esc(item.id)}" class="${state.platforms.has(item.id) ? "is-selected" : ""}">${state.platforms.has(item.id) ? icon("check", 14) : ""}${esc(item.name)}</button>`).join("")}</div></div>
            </div>

            <div class="cr-panel-heading cr-script-heading"><div><span>02</span><h2>待检剧本</h2></div><small>${state.text.length.toLocaleString()} / 300,000 字符</small></div>
            <div class="cr-editor-toolbar">
              <label class="cr-upload">${icon("upload", 16)}上传 Word / PDF / TXT<input id="crFile" type="file" accept=".docx,.pdf,.txt,.md,.json" /></label>
              ${state.filename ? `<span class="cr-file-name">${icon("file-text", 15)}${esc(state.filename)}</span>` : ""}
              <button type="button" class="cr-clear" id="crClear" ${state.text ? "" : "disabled"}>${icon("eraser", 15)}清空</button>
            </div>
            <textarea id="crText" maxlength="300000" placeholder="粘贴完整剧本。${state.view === "rating" ? "评级" : "检测"}会保留原文，不会自动改写或覆盖文件。">${esc(state.text)}</textarea>
            <div class="cr-runbar">
              ${state.view === "rating" ? `<div class="cr-rating-ai">${icon("sparkles", 16)}评级必须由AI通读上下文，规则代码仅负责结构统计与合规门槛。</div>` : `<label class="cr-ai-toggle"><input id="crUseAi" type="checkbox" ${state.useAi ? "checked" : ""} ${catalog.ai?.configured ? "" : "disabled"} /><span></span><div><strong>AI上下文复核</strong><small>${catalog.ai?.configured ? `调用 ${esc(catalog.ai.model || "已配置模型")}，识别机械规则看不懂的语境` : "当前模型未配置，仍可使用零Token规则检测"}</small></div></label>`}
              <button type="button" class="cr-run" id="crRun" ${state.loading || !state.text.trim() ? "disabled" : ""}>${state.loading ? `<span class="cr-button-spinner"></span>${state.view === "rating" ? "评级中" : "检测中"}` : `${icon(state.view === "rating" ? "chart-no-axes-combined" : "scan-search", 18)}开始${state.view === "rating" ? "评级" : "检测"}`}</button>
            </div>
          </section>

          <aside class="cr-result-panel">
            <div class="cr-panel-heading"><div><span>03</span><h2>${state.view === "rating" ? "评级报告" : "检测报告"}</h2></div><small>${selectedPlatformNames().map(esc).join(" · ")}</small></div>
            ${resultMarkup()}
          </aside>
        </div>
        ${historyMarkup()}
        ${state.view === "compliance" ? sourceMarkup() : ""}
        <footer class="cr-disclaimer">${icon("info", 15)}${esc(state.view === "rating" ? "评级用于项目开发与修改决策，不代表任何平台官方评级、签约或流量结果。" : catalog.disclaimer || "本工具仅用于创作风险预检。")}</footer>
      </div>`;
    window.lucide?.createIcons();
    bind();
  }

  function syncText() {
    const input = document.getElementById("crText");
    if (input) state.text = input.value;
  }

  function bind() {
    root.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
      syncText();
      state.view = button.dataset.view;
      state.mode = "standard";
      state.report = null;
      state.repair = null;
      state.selectedFixes = new Set();
      state.error = "";
      render();
    }));
    root.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
      syncText();
      state.mode = button.dataset.mode;
      if (state.mode === "advanced" && state.catalog?.ai?.configured) state.useAi = true;
      state.report = null;
      state.repair = null;
      state.selectedFixes = new Set();
      render();
    }));
    root.querySelectorAll("[data-platform]").forEach((button) => button.addEventListener("click", () => {
      syncText();
      const id = button.dataset.platform;
      if (state.platforms.has(id)) state.platforms.delete(id); else state.platforms.add(id);
      state.report = null;
      render();
    }));
    document.getElementById("crRegion")?.addEventListener("change", (event) => {
      state.region = event.target.value;
      state.report = null;
    });
    document.getElementById("crText")?.addEventListener("input", (event) => {
      state.text = event.target.value;
      const counter = root.querySelector(".cr-script-heading small");
      if (counter) counter.textContent = `${state.text.length.toLocaleString()} / 300,000 字符`;
      const run = document.getElementById("crRun");
      if (run) run.disabled = !state.text.trim();
    });
    document.getElementById("crUseAi")?.addEventListener("change", (event) => {
      state.useAi = event.target.checked;
    });
    document.getElementById("crClear")?.addEventListener("click", () => {
      state.text = "";
      state.filename = "";
      state.report = null;
      state.error = "";
      render();
    });
    document.getElementById("crFile")?.addEventListener("change", uploadFile);
    document.getElementById("crRun")?.addEventListener("click", runReview);
    root.querySelectorAll("[data-repair-key]").forEach((input) => input.addEventListener("change", () => {
      const key = input.dataset.repairKey;
      if (input.checked) state.selectedFixes.add(key); else state.selectedFixes.delete(key);
      input.closest(".cr-priority-fix, .cr-dimension-action")?.classList.toggle("is-selected", input.checked);
      const counter = root.querySelector(".cr-repair-selection");
      if (counter) counter.innerHTML = `已选择 <strong>${state.selectedFixes.size}</strong> / ${repairIssueKeys(state.report).length} 项`;
      const repairButton = document.getElementById("crRepairRun");
      if (repairButton) repairButton.disabled = !state.selectedFixes.size;
    }));
    document.getElementById("crRepairDirection")?.addEventListener("input", (event) => { state.repairDirection = event.target.value; });
    document.getElementById("crSelectAllFixes")?.addEventListener("click", () => {
      const keys = repairIssueKeys(state.report);
      state.selectedFixes = state.selectedFixes.size === keys.length ? new Set() : new Set(keys);
      render();
    });
    document.getElementById("crRepairRun")?.addEventListener("click", runRepair);
    document.getElementById("crApplyRepair")?.addEventListener("click", () => {
      if (!state.repair?.revised_script) return;
      state.text = state.repair.revised_script;
      state.report = null;
      state.repair = null;
      state.selectedFixes = new Set();
      render();
      document.getElementById("crText")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    document.getElementById("crUpgrade")?.addEventListener("click", () => {
      syncText();
      state.mode = "advanced";
      if (state.catalog?.ai?.configured) state.useAi = true;
      state.report = null;
      render();
    });
    root.querySelectorAll("[data-history-open]").forEach((button) => button.addEventListener("click", async () => {
      const records = state.view === "rating" ? state.ratingHistory : state.history;
      const record = records.find((item) => item.id === button.dataset.historyOpen);
      if (!record) return;
      if (state.view === "rating" && !record.script_text) {
        try {
          const detail = await api(`/api/script-rating/history/${encodeURIComponent(record.id)}`);
          Object.assign(record, detail.record || {});
        } catch (error) {
          state.error = error.message;
          render();
          return;
        }
      }
      state.report = record.report || null;
      if (state.view === "rating" && record.script_text) state.text = record.script_text;
      state.mode = record.level || record.mode || "standard";
      state.region = record.region || "国家/全国";
      state.platforms = new Set(record.platforms || []);
      state.error = "";
      state.repair = null;
      state.selectedFixes = new Set();
      render();
      document.querySelector(".cr-result-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    root.querySelectorAll("[data-history-delete]").forEach((button) => button.addEventListener("click", async () => {
      try {
        const base = state.view === "rating" ? "/api/script-rating/history" : "/api/compliance-review/history";
        await api(`${base}/${encodeURIComponent(button.dataset.historyDelete)}`, { method: "DELETE" });
        if (state.view === "rating") state.ratingHistory = state.ratingHistory.filter((item) => item.id !== button.dataset.historyDelete);
        else state.history = state.history.filter((item) => item.id !== button.dataset.historyDelete);
        render();
      } catch (error) {
        state.error = error.message;
        render();
      }
    }));
    document.getElementById("crClearHistory")?.addEventListener("click", async () => {
      try {
        const base = state.view === "rating" ? "/api/script-rating/history" : "/api/compliance-review/history";
        await api(base, { method: "DELETE" });
        if (state.view === "rating") state.ratingHistory = []; else state.history = [];
        render();
      } catch (error) {
        state.error = error.message;
        render();
      }
    });
  }

  async function uploadFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    syncText();
    state.loading = true;
    state.error = "";
    render();
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await api("/api/files/extract-text", { method: "POST", body: form });
      state.text = String(data.text || "");
      state.filename = data.filename || file.name;
      state.report = null;
    } catch (error) {
      state.error = error.message;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function runReview() {
    syncText();
    if (!state.text.trim() || state.loading) return;
    state.loading = true;
    state.error = "";
    state.report = null;
    render();
    try {
      const isRating = state.view === "rating";
      const data = await api(isRating ? "/api/script-rating/check" : "/api/compliance-review/check", {
        method: "POST",
        body: JSON.stringify({
          text: state.text,
          mode: state.mode,
          region: state.region,
          platforms: [...state.platforms],
          use_ai: state.useAi,
          level: state.mode,
          market: state.region,
          filename: state.filename,
        }),
      });
      state.report = data.report;
      state.selectedFixes = new Set((data.report?.priority_fixes || []).slice(0, 3).map((_, index) => `priority:${index}`));
      state.repair = null;
      if (data.history_record) {
        if (isRating) state.ratingHistory = [data.history_record, ...state.ratingHistory.filter((item) => item.id !== data.history_record.id)].slice(0, 50);
        else state.history = [data.history_record, ...state.history.filter((item) => item.id !== data.history_record.id)].slice(0, 50);
      }
    } catch (error) {
      state.error = error.message;
    } finally {
      state.loading = false;
      render();
    }
  }

  async function runRepair() {
    syncText();
    if (!state.text.trim() || !state.report || state.repairLoading) return;
    state.repairLoading = true;
    state.repair = null;
    state.error = "";
    render();
    try {
      const data = await api("/api/script-rating/repair", {
        method: "POST",
        body: JSON.stringify({
          text: state.text,
          report: state.report,
          selected_fixes: [...state.selectedFixes],
          direction: state.repairDirection,
        }),
      });
      state.repair = data.repair;
    } catch (error) {
      state.error = error.message;
    } finally {
      state.repairLoading = false;
      render();
    }
  }

  async function boot() {
    render();
    try {
      const [catalogData, historyData, ratingHistoryData] = await Promise.all([
        api("/api/compliance-review/catalog"),
        api("/api/compliance-review/history"),
        api("/api/script-rating/history"),
      ]);
      state.catalog = catalogData;
      state.history = historyData.records || [];
      state.ratingHistory = ratingHistoryData.records || [];
      render();
    } catch (error) {
      state.error = error.message;
      render();
    }
  }

  boot();
})();
