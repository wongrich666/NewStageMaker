(() => {
  "use strict";

  const config = window.SCRIPT_AUDIT_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const els = {
    title: $("auditTitle"), text: $("auditText"), file: $("auditFile"), count: $("auditCount"),
    run: $("auditRun"), status: $("auditStatus"), loading: $("auditLoading"), result: $("auditResult"),
    loadingTitle: $("auditLoadingTitle"), loadingDetail: $("auditLoadingDetail"), batchProgress: $("auditBatchProgress"),
    reportTitle: $("auditReportTitle"), summary: $("auditSummary"), core: $("auditCoreJudgement"),
    problem: $("auditLargestProblem"), priority: $("auditPriorityFix"), chart: $("auditGlobalChart"),
    pointDetail: $("auditPointDetail"), dimensions: $("auditDimensions"), episodePanel: $("auditEpisodePanel"),
    episodeTabs: $("auditEpisodeTabs"), episodeDetail: $("auditEpisodeDetail"), issues: $("auditIssues"),
    rewrite: $("auditRewrite"), payoffs: $("auditPayoffs"), risks: $("auditRisks"),
    crossPanel: $("auditCrossEpisodePanel"), cross: $("auditCrossEpisode"), warnings: $("auditWarnings"),
    downloadText: $("auditDownloadText"), downloadJson: $("auditDownloadJson")
  };
  let latestPayload = null;
  let activeRunId = "";
  let activeRunFailed = false;
  let pollTimer = null;
  const ACTIVE_RUN_KEY = "scriptAudit.activeRun.v2";

  const text = (value, fallback = "—") => {
    if (value === null || value === undefined || value === "") return fallback;
    if (Array.isArray(value)) return value.map((item) => text(item, "")).filter(Boolean).join("、") || fallback;
    if (typeof value === "object") return Object.values(value).map((item) => text(item, "")).filter(Boolean).join("；") || fallback;
    return String(value);
  };

  const node = (tag, className, content) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  };

  const setStatus = (message, kind = "") => {
    els.status.textContent = message;
    els.status.className = `audit-status${kind ? ` ${kind}` : ""}`;
  };

  const apiUrl = (path = "/api/script-audit/run") => {
    const url = new URL(path, window.location.origin);
    const token = new URLSearchParams(window.location.search).get("auth_token") || config.authToken || "";
    if (token) url.searchParams.set("auth_token", token);
    return url.toString();
  };

  const safeFilename = (suffix) => {
    const base = (els.title.value || "剧本心电图报告").trim().replace(/[\\/:*?"<>|]+/g, "_");
    return `${base || "剧本心电图报告"}.${suffix}`;
  };

  const download = (content, type, filename) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const scoreColor = (value) => value > 0
    ? "var(--audit-chart-positive, #1f8a5b)"
    : value < 0
      ? "var(--audit-chart-negative, #cf4b45)"
      : "var(--audit-chart-neutral, #888d84)";

  function renderChart(container, points, detailTarget) {
    container.replaceChildren();
    if (!Array.isArray(points) || !points.length) {
      container.append(node("p", "audit-record empty", "没有可展示的心电节点"));
      return;
    }
    const ns = "http://www.w3.org/2000/svg";
    const width = Math.max(760, points.length * 72);
    const height = 310;
    const padX = 44;
    const padTop = 24;
    const padBottom = 50;
    const plotHeight = height - padTop - padBottom;
    const y = (value) => padTop + ((5 - Number(value || 0)) / 10) * plotHeight;
    const x = (index) => points.length === 1 ? width / 2 : padX + index * ((width - padX * 2) / (points.length - 1));
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.style.minWidth = `${width}px`;

    [-5, -3, 0, 3, 5].forEach((tick) => {
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", padX); line.setAttribute("x2", width - padX);
      line.setAttribute("y1", y(tick)); line.setAttribute("y2", y(tick));
      line.setAttribute("stroke", tick === 0 ? "var(--audit-chart-grid-strong, rgba(32,35,31,.35))" : "var(--audit-chart-grid, rgba(32,35,31,.09))");
      line.setAttribute("stroke-width", tick === 0 ? "1.5" : "1");
      svg.append(line);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", 9); label.setAttribute("y", y(tick) + 4);
      label.setAttribute("fill", "var(--audit-chart-muted, #7a7d76)"); label.setAttribute("font-size", "11");
      label.textContent = tick > 0 ? `+${tick}` : String(tick);
      svg.append(label);
    });

    const polyline = document.createElementNS(ns, "polyline");
    polyline.setAttribute("points", points.map((point, index) => `${x(index)},${y(point.ecg_value)}`).join(" "));
    polyline.setAttribute("fill", "none"); polyline.setAttribute("stroke", "var(--audit-chart-line, #30332e)");
    polyline.setAttribute("stroke-width", "2.5"); polyline.setAttribute("stroke-linejoin", "round");
    svg.append(polyline);

    points.forEach((point, index) => {
      const group = document.createElementNS(ns, "g");
      group.classList.add("audit-chart-button");
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      const circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", x(index)); circle.setAttribute("cy", y(point.ecg_value)); circle.setAttribute("r", "6");
      circle.setAttribute("fill", scoreColor(Number(point.ecg_value || 0)));
      circle.setAttribute("stroke", "var(--audit-chart-point-ring, #fff)"); circle.setAttribute("stroke-width", "2");
      const title = document.createElementNS(ns, "title");
      title.textContent = `${text(point.x_label)}：${Number(point.ecg_value || 0) > 0 ? "+" : ""}${Number(point.ecg_value || 0)} ${text(point.audit_reason, "")}`;
      circle.append(title);
      group.append(circle);
      if (points.length <= 30 || index % Math.ceil(points.length / 24) === 0 || index === points.length - 1) {
        const label = document.createElementNS(ns, "text");
        label.setAttribute("x", x(index)); label.setAttribute("y", height - 20);
        label.setAttribute("fill", "var(--audit-chart-muted, #747870)"); label.setAttribute("font-size", "10"); label.setAttribute("text-anchor", "middle");
        label.textContent = text(point.x_label, String(index + 1)).slice(0, 9);
        group.append(label);
      }
      const showDetail = () => {
        detailTarget.replaceChildren();
        const heading = node("strong", "", `${text(point.x_label)} · ${Number(point.ecg_value || 0) > 0 ? "+" : ""}${Number(point.ecg_value || 0)}`);
        detailTarget.append(heading, document.createTextNode(`　${text(point.audit_reason || point.commercial_effect)}`));
        if (point.fix_suggestion) detailTarget.append(document.createElement("br"), document.createTextNode(`修改建议：${point.fix_suggestion}`));
        container.scrollLeft = Math.max(0, x(index) - container.clientWidth / 2);
      };
      group.addEventListener("click", showDetail);
      group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showDetail(); } });
      svg.append(group);
    });
    container.append(svg);
  }

  function renderDimensions(container, dimensions) {
    container.replaceChildren();
    (dimensions || []).forEach((item) => {
      const card = node("div", "audit-dimension-card");
      const score = node("div", "audit-dimension-score");
      score.append(node("strong", "", text(item.score, "0")), node("span", "", `/ ${text(item.max_score, "0")}　${text(item.dimension_name)}`));
      const track = node("div", "audit-score-track");
      const fill = node("i");
      const percent = Math.max(0, Math.min(100, Number(item.score || 0) / Math.max(1, Number(item.max_score || 1)) * 100));
      fill.style.width = `${percent}%`;
      track.append(fill);
      card.append(score, track, node("p", "", text(item.summary || item.deduction_reason)));
      if (item.fix_direction) card.append(node("p", "", `建议：${item.fix_direction}`));
      container.append(card);
    });
  }

  const firstMeaningful = (record, keys) => {
    for (const key of keys) if (record && record[key] !== undefined && record[key] !== null && record[key] !== "") return record[key];
    return "";
  };

  function renderRecords(container, records, kind) {
    container.replaceChildren();
    if (!Array.isArray(records) || !records.length) {
      container.append(node("div", "audit-record empty", "本项未发现需单列的内容"));
      return;
    }
    const titleKeys = ["title", "task", "action", "issue", "risk", "name", "short_label", "point_name", "description"];
    const bodyKeys = ["description", "evidence", "reason", "impact", "fix_suggestion", "suggestion", "expected_effect", "original_text_excerpt", "location"];
    records.forEach((record, index) => {
      const card = node("div", "audit-record");
      const titleValue = typeof record === "object" ? firstMeaningful(record, titleKeys) : record;
      card.append(node("strong", "", text(titleValue, `${kind} ${index + 1}`)));
      if (typeof record === "object") {
        const body = bodyKeys.map((key) => record[key]).filter((value) => value !== undefined && value !== null && value !== "").map((value) => text(value, "")).filter(Boolean).join("\n");
        if (body && body !== String(titleValue)) card.append(node("p", "", body));
      }
      container.append(card);
    });
  }

  function renderEpisode(episode) {
    els.episodeDetail.replaceChildren();
    const summary = node("div", "audit-episode-summary");
    const score = node("div", "audit-episode-score");
    score.append(node("strong", "", text(episode.episode_score, "0")), node("span", "", `/ 100 · ${text(episode.level)}`));
    const facts = node("div", "audit-episode-facts");
    [
      ["核心判断", episode.core_judgement], ["主要钩子", episode.main_hook],
      ["主要冲突", episode.main_conflict], ["主要爽点", episode.main_payoff],
      ["最大流失点", episode.largest_retention_loss], ["下集拉力", episode.next_episode_pull],
      ["优先修改", episode.priority_fix], ["保留亮点", episode.best_retained_part],
      ["主导情绪", episode.emotional_review && episode.emotional_review.dominant_emotion],
      ["情绪兑现", episode.emotional_review && episode.emotional_review.emotional_payoff],
      ["承接顺滑度", episode.continuity_review && episode.continuity_review.handoff_smoothness_score !== undefined
        ? `${episode.continuity_review.handoff_smoothness_score}/10` : ""],
      ["承接断点", episode.continuity_review && episode.continuity_review.break_points]
    ].forEach(([label, value]) => {
      const box = node("div"); box.append(node("span", "", label), node("p", "", text(value))); facts.append(box);
    });
    summary.append(score, facts);
    els.episodeDetail.append(summary);
    const chart = node("div", "audit-chart audit-episode-chart");
    const detail = node("div", "audit-point-detail", "点击单集曲线节点查看详情。");
    els.episodeDetail.append(chart, detail);
    renderChart(chart, episode.ecg_points || [], detail);
    const dimensions = node("div", "audit-dimension-grid");
    els.episodeDetail.append(dimensions);
    renderDimensions(dimensions, episode.dimension_scores || []);
  }

  function renderEpisodes(episodes) {
    els.episodeTabs.replaceChildren();
    if (!Array.isArray(episodes) || !episodes.length) {
      els.episodePanel.classList.add("hidden");
      return;
    }
    els.episodePanel.classList.remove("hidden");
    episodes.forEach((episode, index) => {
      const button = node("button", index === 0 ? "active" : "", `第${episode.episode_no || index + 1}集`);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.addEventListener("click", () => {
        els.episodeTabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        renderEpisode(episode);
      });
      els.episodeTabs.append(button);
    });
    renderEpisode(episodes[0]);
  }

  function renderCrossEpisode(data) {
    els.cross.replaceChildren();
    const entries = Object.entries(data || {}).filter(([, value]) => value !== "" && value !== null && value !== undefined && (!Array.isArray(value) || value.length));
    if (!entries.length) { els.crossPanel.classList.add("hidden"); return; }
    els.crossPanel.classList.remove("hidden");
    const labels = {
      retention_curve_summary: "留存曲线", weak_episode_numbers: "薄弱集数", payoff_distribution_problem: "爽点分布",
      hook_continuity_problem: "钩子连续性", character_arc_problem: "人物弧线", fix_suggestion: "总体修复建议",
      episode_score_trend: "单集分数趋势", best_episode_no: "最佳集", best_episode_reason: "最佳集理由",
      weakest_episode_no: "最弱集", weakest_episode_reason: "最弱集理由", score_gap_analysis: "分差分析",
      global_dropoff_pattern: "全局流失模式"
    };
    entries.forEach(([key, value]) => {
      const wrapper = node("div"); const dl = node("dl");
      dl.append(node("dt", "", labels[key] || key), node("dd", "", text(value))); wrapper.append(dl); els.cross.append(wrapper);
    });
  }

  function renderResult(payload) {
    latestPayload = payload;
    const audit = payload.audit || {};
    const view = payload.view || {};
    const overall = audit.overall || {};
    const meta = audit.meta || {};
    els.reportTitle.textContent = `《${text(meta.script_title, "未命名剧本")}》审核报告`;
    els.summary.replaceChildren();
    (view.summary_cards || []).forEach((item) => {
      const card = node("div", "audit-summary-card");
      card.append(node("span", "", text(item.label)), node("strong", "", text(item.value, "0")), node("em", "", text(item.suffix, "")));
      els.summary.append(card);
    });
    els.core.textContent = text(overall.core_judgement);
    els.problem.textContent = text(overall.largest_problem);
    els.priority.textContent = text(overall.priority_fix);
    renderChart(els.chart, view.ecg_chart && view.ecg_chart.points || [], els.pointDetail);
    renderDimensions(els.dimensions, view.dimension_cards || []);
    renderEpisodes(view.episode_cards || []);
    renderRecords(els.issues, view.issue_cards, "问题");
    renderRecords(els.rewrite, view.rewrite_tasks, "任务");
    renderRecords(els.payoffs, view.satisfying_point_cards, "爽点");
    renderRecords(els.risks, view.risk_cards, "风险");
    renderCrossEpisode(view.cross_episode_analysis || {});
    const warnings = payload.warnings || [];
    els.warnings.classList.toggle("hidden", !warnings.length);
    els.warnings.textContent = warnings.length ? `兼容性提示：${warnings.join("；")}` : "";
    els.result.classList.remove("hidden");
    requestAnimationFrame(() => els.result.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  const rememberActiveRun = (runId) => {
    activeRunId = String(runId || "");
    try {
      if (activeRunId) window.localStorage.setItem(ACTIVE_RUN_KEY, activeRunId);
      else window.localStorage.removeItem(ACTIVE_RUN_KEY);
    } catch (_) { /* localStorage is optional */ }
  };

  const setRunningUi = (running) => {
    els.run.disabled = running;
    els.run.textContent = running ? "分批检测中…" : (activeRunFailed ? "继续检测" : "开始检测");
    els.loading.classList.toggle("hidden", !running);
  };

  const stopPolling = () => {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = null;
  };

  async function requestApi(path, options = {}) {
    const response = await fetch(apiUrl(path), {
      credentials: "same-origin",
      headers: { "Accept": "application/json", ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
      ...options
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) throw new Error(payload.message || `请求失败（HTTP ${response.status}）`);
    return payload;
  }

  function updateRunProgress(payload) {
    const completed = Array.isArray(payload.completed_episode_numbers) ? payload.completed_episode_numbers.length : 0;
    const total = Number(payload.total_episodes || 0);
    const start = Number(payload.current_batch_start || 0);
    const end = Number(payload.current_batch_end || 0);
    const percent = Number(payload.progress_percent || 0);
    els.batchProgress.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    els.loadingTitle.textContent = start > 0 ? `正在审核第 ${start}～${end} 集` : "正在准备分批审核";
    els.loadingDetail.textContent = `已完成 ${completed}/${total || "?"} 集 · ${payload.completed_batches || 0}/${payload.total_batches || "?"} 批；刷新页面也会继续运行。`;
    setStatus(`心电图审核进度：${completed}/${total || "?"} 集（${percent}%）`);
  }

  async function pollActiveRun() {
    stopPolling();
    if (!activeRunId) return;
    try {
      const payload = await requestApi(`/api/script-audit/runs/${encodeURIComponent(activeRunId)}`);
      if (payload.status === "succeeded") {
        activeRunFailed = false;
        renderResult(payload);
        setStatus("检测完成，已生成全剧心电图和逐集评分报告。", "success");
        rememberActiveRun("");
        setRunningUi(false);
        return;
      }
      if (payload.status === "failed") {
        activeRunFailed = true;
        updateRunProgress(payload);
        const debugHint = payload.debug_file ? ` 调试记录：${payload.debug_file}` : "";
        setStatus(`${payload.error || "当前批次审核失败，可以点击继续检测从失败批次重试。"}${debugHint}`, "error");
        setRunningUi(false);
        return;
      }
      activeRunFailed = false;
      setRunningUi(true);
      updateRunProgress(payload);
      pollTimer = window.setTimeout(pollActiveRun, 1800);
    } catch (error) {
      setStatus(error && error.message ? error.message : "进度读取失败，正在重试…", "error");
      pollTimer = window.setTimeout(pollActiveRun, 3000);
    }
  }

  async function runAudit() {
    if (activeRunId && activeRunFailed) {
      try {
        activeRunFailed = false;
        setRunningUi(true);
        await requestApi(`/api/script-audit/runs/${encodeURIComponent(activeRunId)}/resume`, { method: "POST", body: JSON.stringify({}) });
        setStatus("已从失败批次继续审核…");
        await pollActiveRun();
      } catch (error) {
        activeRunFailed = true;
        setRunningUi(false);
        setStatus(error && error.message ? error.message : "任务恢复失败。", "error");
      }
      return;
    }
    const scriptText = els.text.value.trim();
    if (!scriptText) { setStatus("请先填写需要检测的剧本正文。", "error"); els.text.focus(); return; }
    if (scriptText.length < 50) { setStatus("剧本文本至少需要 50 个字符。", "error"); els.text.focus(); return; }
    setRunningUi(true);
    els.result.classList.add("hidden");
    els.batchProgress.style.width = "0%";
    setStatus("正在识别集标题并创建分批审核任务…");
    try {
      const payload = await requestApi("/api/script-audit/run", {
        method: "POST",
        body: JSON.stringify({ script_title: els.title.value.trim(), script_text: scriptText })
      });
      rememberActiveRun(payload.run_id);
      activeRunFailed = false;
      updateRunProgress(payload);
      await pollActiveRun();
    } catch (error) {
      setRunningUi(false);
      setStatus(error && error.message ? error.message : "检测失败，请稍后重试。", "error");
    }
  }

  els.text.addEventListener("input", () => {
    els.count.textContent = `${els.text.value.length} / 300000 字符`;
    if (activeRunFailed) {
      activeRunFailed = false;
      rememberActiveRun("");
      setRunningUi(false);
    }
  });
  els.file.addEventListener("change", async () => {
    const file = els.file.files && els.file.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { setStatus("文件超过 10MB，请改为精简后的文本。", "error"); return; }
    try {
      setStatus(`正在解析 ${file.name}…`);
      const form = new FormData();
      form.append("file", file);
      const payload = await requestApi("/api/script-audit/extract-file", { method: "POST", body: form });
      els.text.value = payload.script_text || "";
      if (!els.title.value) els.title.value = payload.script_title || file.name.replace(/\.[^.]+$/, "");
      els.text.dispatchEvent(new Event("input"));
      setStatus(`已导入 ${file.name}`);
    } catch (_) { setStatus("文件读取失败，请改为粘贴文本。", "error"); }
  });
  els.run.addEventListener("click", runAudit);
  els.downloadText.addEventListener("click", () => {
    if (latestPayload) download((latestPayload.view && latestPayload.view.export_text) || "", "text/plain;charset=utf-8", safeFilename("txt"));
  });
  els.downloadJson.addEventListener("click", () => {
    if (latestPayload) download(JSON.stringify(latestPayload.audit, null, 2), "application/json;charset=utf-8", safeFilename("json"));
  });
  try { activeRunId = window.localStorage.getItem(ACTIVE_RUN_KEY) || ""; } catch (_) { activeRunId = ""; }
  if (activeRunId) {
    setRunningUi(true);
    setStatus("正在恢复上次的心电图审核进度…");
    pollActiveRun();
  }
})();
