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
    downloadText: $("auditDownloadText"), downloadJson: $("auditDownloadJson"),
    assetList: $("auditAssetList"), assetsRefresh: $("auditAssetsRefresh")
  };
  let latestPayload = null;
  let activeRunId = "";
  let activeRunFailed = false;
  let pollTimer = null;
  let assetOpenRevision = 0;
  const ACTIVE_RUN_KEY = "scriptAudit.activeRun.v2";

  const requestedAssetId = () => new URLSearchParams(window.location.search).get("audit_asset_id") || "";

  const syncAssetUrl = (runId) => {
    const url = new URL(window.location.href);
    if (runId) url.searchParams.set("audit_asset_id", runId);
    else url.searchParams.delete("audit_asset_id");
    window.history.replaceState({}, "", url);
  };

  const formatAssetTime = (value) => {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
  };

  const statusLabel = (status) => ({
    succeeded: "评分完成", running: "评分中", pending: "等待运行", failed: "可继续"
  }[status] || "已保存");

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
    const base = (els.title.value || "文脉检测报告").trim().replace(/[\\/:*?"<>|]+/g, "_");
    return `${base || "文脉检测报告"}.${suffix}`;
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
    if (container._auditResizeObserver) {
      container._auditResizeObserver.disconnect();
      container._auditResizeObserver = null;
    }
    container.replaceChildren();
    if (!Array.isArray(points) || !points.length) {
      container.append(node("p", "audit-record empty", "没有可展示的心电节点"));
      return;
    }
    const toolbar = node("div", "audit-chart-toolbar");
    const hint = node("span", "", "总览模式 · 展开后可按住图表左右拖动");
    const actions = node("div", "audit-chart-actions");
    const navigation = node("div", "audit-chart-navigation hidden");
    const previous = node("button", "audit-chart-arrow", "←");
    const next = node("button", "audit-chart-arrow", "→");
    previous.type = "button";
    previous.setAttribute("aria-label", "向左浏览心电节点");
    next.type = "button";
    next.setAttribute("aria-label", "向右浏览心电节点");
    navigation.append(previous, next);
    const toggle = node("button", "audit-chart-toggle", "展开节点");
    toggle.type = "button";
    toggle.setAttribute("aria-pressed", "false");
    const scrollArea = node("div", "audit-chart-scroll");
    scrollArea.setAttribute("tabindex", "0");
    scrollArea.setAttribute("aria-label", "心电图横向浏览区");
    actions.append(navigation, toggle);
    toolbar.append(hint, actions);
    container.append(toolbar, scrollArea);

    const ns = "http://www.w3.org/2000/svg";
    const height = 310;
    const padX = 44;
    const padTop = 24;
    const padBottom = 50;
    const plotHeight = height - padTop - padBottom;
    const y = (value) => padTop + ((5 - Number(value || 0)) / 10) * plotHeight;
    let expanded = false;
    let suppressClickUntil = 0;
    let lastViewportWidth = 0;

    const viewportWidth = () => Math.max(320, Math.floor(scrollArea.clientWidth || container.clientWidth || 760));
    const updateNavigation = () => {
      previous.disabled = !expanded || scrollArea.scrollLeft <= 1;
      next.disabled = !expanded || scrollArea.scrollLeft >= scrollArea.scrollWidth - scrollArea.clientWidth - 1;
    };

    const draw = () => {
      const visibleWidth = viewportWidth();
      lastViewportWidth = visibleWidth;
      const width = expanded
        ? Math.max(visibleWidth, Math.min(6400, Math.max(760, points.length * 38)))
        : visibleWidth;
      const x = (index) => points.length === 1 ? width / 2 : padX + index * ((width - padX * 2) / (points.length - 1));
      const svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("width", String(width));
      svg.setAttribute("height", String(height));
      svg.setAttribute("preserveAspectRatio", "xMinYMid meet");
      svg.style.width = expanded ? `${width}px` : "100%";
      svg.style.height = `${height}px`;

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

      const maximumLabels = Math.max(5, Math.floor(width / 86));
      const labelInterval = Math.max(1, Math.ceil(points.length / maximumLabels));
      points.forEach((point, index) => {
        const group = document.createElementNS(ns, "g");
        group.classList.add("audit-chart-button");
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        const circle = document.createElementNS(ns, "circle");
        circle.setAttribute("cx", x(index)); circle.setAttribute("cy", y(point.ecg_value)); circle.setAttribute("r", expanded ? "5" : "4.5");
        circle.setAttribute("fill", scoreColor(Number(point.ecg_value || 0)));
        circle.setAttribute("stroke", "var(--audit-chart-point-ring, #fff)"); circle.setAttribute("stroke-width", "2");
        const title = document.createElementNS(ns, "title");
        title.textContent = `${text(point.x_label)}：${Number(point.ecg_value || 0) > 0 ? "+" : ""}${Number(point.ecg_value || 0)} ${text(point.audit_reason, "")}`;
        circle.append(title);
        group.append(circle);
        if (index % labelInterval === 0 || index === points.length - 1) {
          const label = document.createElementNS(ns, "text");
          label.setAttribute("x", x(index)); label.setAttribute("y", height - 20);
          label.setAttribute("fill", "var(--audit-chart-muted, #747870)"); label.setAttribute("font-size", "10"); label.setAttribute("text-anchor", "middle");
          label.textContent = text(point.x_label, String(index + 1)).slice(0, 9);
          group.append(label);
        }
        const showDetail = () => {
          if (Date.now() < suppressClickUntil) return;
          detailTarget.replaceChildren();
          const heading = node("strong", "", `${text(point.x_label)} · ${Number(point.ecg_value || 0) > 0 ? "+" : ""}${Number(point.ecg_value || 0)}`);
          detailTarget.append(heading, document.createTextNode(`　${text(point.audit_reason || point.commercial_effect)}`));
          if (point.fix_suggestion) detailTarget.append(document.createElement("br"), document.createTextNode(`修改建议：${point.fix_suggestion}`));
          if (expanded) scrollArea.scrollTo({ left: Math.max(0, x(index) - scrollArea.clientWidth / 2), behavior: "smooth" });
        };
        group.addEventListener("click", showDetail);
        group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showDetail(); } });
        svg.append(group);
      });
      scrollArea.replaceChildren(svg);
      requestAnimationFrame(updateNavigation);
    };

    let dragStartX = 0;
    let dragStartScroll = 0;
    let dragging = false;
    scrollArea.addEventListener("pointerdown", (event) => {
      if (!expanded || event.button !== 0) return;
      dragStartX = event.clientX;
      dragStartScroll = scrollArea.scrollLeft;
      dragging = false;
      scrollArea.setPointerCapture(event.pointerId);
    });
    scrollArea.addEventListener("pointermove", (event) => {
      if (!scrollArea.hasPointerCapture(event.pointerId)) return;
      const movement = event.clientX - dragStartX;
      if (Math.abs(movement) > 4) dragging = true;
      if (dragging) {
        scrollArea.classList.add("dragging");
        scrollArea.scrollLeft = dragStartScroll - movement;
      }
    });
    const stopDragging = (event) => {
      if (!scrollArea.hasPointerCapture(event.pointerId)) return;
      scrollArea.releasePointerCapture(event.pointerId);
      scrollArea.classList.remove("dragging");
      if (dragging) suppressClickUntil = Date.now() + 180;
      dragging = false;
    };
    scrollArea.addEventListener("pointerup", stopDragging);
    scrollArea.addEventListener("pointercancel", stopDragging);
    scrollArea.addEventListener("scroll", updateNavigation, { passive: true });
    previous.addEventListener("click", () => scrollArea.scrollBy({ left: -scrollArea.clientWidth * .78, behavior: "smooth" }));
    next.addEventListener("click", () => scrollArea.scrollBy({ left: scrollArea.clientWidth * .78, behavior: "smooth" }));

    toggle.addEventListener("click", () => {
      expanded = !expanded;
      toggle.textContent = expanded ? "收起总览" : "展开节点";
      toggle.setAttribute("aria-pressed", String(expanded));
      hint.textContent = expanded ? "详细模式 · 拖动图表或使用底部滚动条查看节点" : "总览模式 · 展开后可按住图表左右拖动";
      container.classList.toggle("expanded", expanded);
      navigation.classList.toggle("hidden", !expanded);
      scrollArea.scrollLeft = 0;
      draw();
    });

    draw();
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(() => {
        const width = viewportWidth();
        if (!expanded && Math.abs(width - lastViewportWidth) > 4) draw();
      });
      observer.observe(container);
      container._auditResizeObserver = observer;
    }
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
    const source = data && typeof data === "object" ? data : {};
    const hasValue = (value) => value !== "" && value !== null && value !== undefined && (!Array.isArray(value) || value.length);
    const hasContent = Object.values(source).some(hasValue);
    if (!hasContent) { els.crossPanel.classList.add("hidden"); return; }
    els.crossPanel.classList.remove("hidden");

    const appendNarrative = (label, value, className = "") => {
      if (!hasValue(value)) return;
      const card = node("section", `audit-cross-card${className ? ` ${className}` : ""}`);
      card.append(node("h4", "", label), node("p", "", text(value)));
      els.cross.append(card);
    };

    let retentionSummary = source.retention_curve_summary;
    if (Array.isArray(source.episode_score_trend) && source.episode_score_trend.length && typeof retentionSummary === "string" && retentionSummary.includes("→")) {
      const narrative = retentionSummary.split("。").slice(1).map((item) => item.trim()).filter(Boolean).join("。");
      if (narrative) retentionSummary = `${narrative}。`;
    }
    appendNarrative("留存曲线判断", retentionSummary, "audit-cross-wide");

    const trend = Array.isArray(source.episode_score_trend)
      ? source.episode_score_trend.map((item, index) => {
        const record = item && typeof item === "object" ? item : {};
        const episodeNo = Number(record.episode_no ?? record.episode ?? index + 1);
        const score = Number(record.score ?? record.episode_score ?? record.value);
        return { episodeNo, score };
      }).filter((item) => Number.isFinite(item.episodeNo) && item.episodeNo > 0 && Number.isFinite(item.score))
      : [];
    if (trend.length) {
      const card = node("section", "audit-cross-card audit-cross-wide audit-score-trend-card");
      const heading = node("div", "audit-cross-card-head");
      heading.append(node("h4", "", "单集分数趋势"));
      const average = trend.reduce((sum, item) => sum + item.score, 0) / trend.length;
      heading.append(node("span", "audit-cross-meta", `${trend.length} 集 · 平均 ${average.toFixed(1)} 分`));
      const list = node("ol", "audit-score-trend-list");
      trend.forEach(({ episodeNo, score }) => {
        const tone = score >= 80 ? "strong" : score >= 70 ? "steady" : score >= 60 ? "watch" : "risk";
        const status = score >= 80 ? "强" : score >= 70 ? "稳" : score >= 60 ? "待提升" : "高风险";
        const item = node("li", `audit-score-trend-item ${tone}`);
        const episode = node("span", "audit-score-episode", `第${episodeNo}集`);
        const meter = node("span", "audit-score-mini-track");
        const fill = node("i");
        fill.style.width = `${Math.max(0, Math.min(100, score))}%`;
        meter.append(fill);
        const value = node("strong", "audit-score-value", `${score.toFixed(Number.isInteger(score) ? 0 : 1)}分`);
        const badge = node("em", "audit-score-status", status);
        item.append(episode, meter, value, badge);
        list.append(item);
      });
      card.append(heading, list);
      els.cross.append(card);
    }

    const weakEpisodes = Array.isArray(source.weak_episode_numbers) ? source.weak_episode_numbers : [];
    if (weakEpisodes.length) {
      const card = node("section", "audit-cross-card audit-cross-wide");
      card.append(node("h4", "", "薄弱集数"));
      const pills = node("div", "audit-episode-pill-list");
      weakEpisodes.forEach((episodeNo) => pills.append(node("span", "", `第${episodeNo}集`)));
      card.append(pills);
      els.cross.append(card);
    }

    const highlights = [
      ["最佳单集", source.best_episode_no, source.best_episode_reason, "best"],
      ["最弱单集", source.weakest_episode_no, source.weakest_episode_reason, "weakest"]
    ];
    highlights.forEach(([label, episodeNo, reason, tone]) => {
      if (!(Number(episodeNo) > 0) && !hasValue(reason)) return;
      const card = node("section", `audit-cross-card audit-cross-highlight ${tone}`);
      card.append(node("h4", "", label));
      if (Number(episodeNo) > 0) card.append(node("strong", "audit-cross-episode-number", `第${episodeNo}集`));
      if (hasValue(reason)) card.append(node("p", "", text(reason)));
      els.cross.append(card);
    });

    [
      ["爽点分布", source.payoff_distribution_problem],
      ["钩子连续性", source.hook_continuity_problem],
      ["人物弧线", source.character_arc_problem],
      ["集间分差", source.score_gap_analysis],
      ["全局流失模式", source.global_dropoff_pattern]
    ].forEach(([label, value]) => appendNarrative(label, value));
    appendNarrative("总体修复建议", source.fix_suggestion, "audit-cross-wide audit-cross-priority");

    const boundaries = Array.isArray(source.batch_boundaries) ? source.batch_boundaries : [];
    if (boundaries.length) {
      const card = node("section", "audit-cross-card audit-cross-wide audit-boundary-card");
      const heading = node("div", "audit-cross-card-head");
      heading.append(node("h4", "", "批次边界承接"), node("span", "audit-cross-meta", `${boundaries.length} 个边界 · 点击展开详情`));
      const list = node("div", "audit-boundary-list");
      boundaries.forEach((boundary) => {
        if (!boundary || typeof boundary !== "object") return;
        const previous = Number(boundary.previous_episode_no || 0);
        const current = Number(boundary.current_episode_no || 0);
        const score = Number(boundary.handoff_smoothness_score);
        const details = node("details", "audit-boundary-item");
        const summary = node("summary");
        const title = previous > 0 ? `第${previous}集 → 第${current}集` : `第${current || 1}集开场`;
        summary.append(node("span", "", title));
        if (previous > 0 && Number.isFinite(score)) {
          const tone = score >= 8 ? "strong" : score >= 6 ? "steady" : score >= 4 ? "watch" : "risk";
          summary.append(node("strong", `audit-boundary-score ${tone}`, `${score}/10`));
        }
        const body = node("div", "audit-boundary-body");
        [
          ["剧情承接", boundary.plot_continuity],
          ["人物状态", boundary.character_state_continuity],
          ["信息承接", boundary.information_continuity],
          ["情绪承接", boundary.emotion_continuity]
        ].forEach(([label, value]) => {
          if (!hasValue(value)) return;
          const row = node("div", "audit-boundary-fact");
          row.append(node("span", "", label), node("p", "", text(value)));
          body.append(row);
        });
        const breakPoints = Array.isArray(boundary.break_points) ? boundary.break_points : [];
        if (breakPoints.length) {
          const section = node("div", "audit-boundary-breaks");
          section.append(node("span", "", "承接断点"));
          const bullets = node("ul");
          breakPoints.forEach((item) => {
            const description = item && typeof item === "object"
              ? firstMeaningful(item, ["description", "issue", "title", "type"])
              : item;
            bullets.append(node("li", "", text(description)));
          });
          section.append(bullets);
          body.append(section);
        }
        if (hasValue(boundary.fix_suggestion)) {
          const fix = node("div", "audit-boundary-fix");
          fix.append(node("span", "", "修复建议"), node("p", "", text(boundary.fix_suggestion)));
          body.append(fix);
        }
        details.append(summary, body);
        list.append(details);
      });
      card.append(heading, list);
      els.cross.append(card);
    }
  }

  function renderResult(payload) {
    latestPayload = payload;
    const audit = payload.audit || {};
    const view = payload.view || {};
    const overall = audit.overall || {};
    const meta = audit.meta || {};
    els.result.classList.remove("hidden");
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
    requestAnimationFrame(() => els.result.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function renderAssets(assets) {
    if (!els.assetList) return;
    els.assetList.replaceChildren();
    if (!Array.isArray(assets) || !assets.length) {
      els.assetList.append(node("div", "audit-asset-empty", "暂无测评资产。上传并开始检测后会自动保存在这里。"));
      return;
    }
    assets.forEach((asset) => {
      const card = node("article", `audit-asset-card${asset.run_id === activeRunId ? " active" : ""}`);
      card.append(node("div", "audit-asset-title", `《${text(asset.script_title, "未命名剧本")}》`));
      const badge = node("span", `audit-asset-status ${asset.status || ""}`, statusLabel(asset.status));
      card.append(badge);
      const meta = node("div", "audit-asset-meta");
      meta.append(
        node("span", "", `${Number(asset.total_episodes || 0)} 集`),
        node("span", "", `${Number(asset.progress_percent || 0)}%`)
      );
      if (asset.total_score !== null && asset.total_score !== undefined) meta.append(node("span", "", `${asset.total_score} 分${asset.level ? ` · ${asset.level}` : ""}`));
      if (asset.updated_at) meta.append(node("span", "", formatAssetTime(asset.updated_at)));
      card.append(meta);
      const actions = node("div", "audit-asset-actions");
      const openButton = node("button", "audit-asset-open", asset.status === "succeeded" ? "打开评分结果" : asset.status === "failed" ? "打开并继续" : "查看进度");
      openButton.type = "button";
      openButton.addEventListener("click", () => openAsset(asset.run_id, { recover: true }));
      const deleteButton = node("button", "audit-asset-delete", "删除");
      deleteButton.type = "button";
      const isRunning = asset.status === "pending" || asset.status === "running";
      deleteButton.disabled = isRunning;
      deleteButton.title = isRunning ? "评分运行中，完成或失败后才能删除" : `删除《${text(asset.script_title, "未命名剧本")}》的评分记录`;
      deleteButton.addEventListener("click", () => deleteAsset(asset, deleteButton));
      actions.append(openButton, deleteButton);
      card.append(actions);
      els.assetList.append(card);
    });
  }

  async function loadAssets() {
    if (!els.assetList) return;
    try {
      const payload = await requestApi("/api/script-audit/assets");
      renderAssets(payload.assets || []);
    } catch (error) {
      els.assetList.replaceChildren(node("div", "audit-asset-empty", error && error.message ? error.message : "测评资产读取失败。"));
    }
  }

  async function openAsset(runId, options = {}) {
    const normalized = String(runId || "");
    if (!normalized) return;
    const revision = ++assetOpenRevision;
    stopPolling();
    activeRunFailed = false;
    rememberActiveRun(normalized);
    syncAssetUrl(normalized);
    setStatus("正在打开已保存的测评资产…");
    try {
      const query = options.recover ? "?recover=1" : "";
      const payload = await requestApi(`/api/script-audit/runs/${encodeURIComponent(normalized)}${query}`);
      if (revision !== assetOpenRevision || activeRunId !== normalized) return;
      els.title.value = payload.script_title || "";
      els.text.value = payload.script_text || "";
      els.count.textContent = `${els.text.value.length} / 300000 字符`;
      if (payload.status === "succeeded") {
        activeRunFailed = false;
        setRunningUi(false);
        renderResult(payload);
        setStatus("已打开保存的评分结果；不会重复调用工作流。", "success");
      } else if (payload.status === "failed") {
        activeRunFailed = true;
        updateRunProgress(payload);
        setRunningUi(false);
        setStatus(payload.error || "已恢复失败批次，可点击继续检测。", "error");
      } else {
        setRunningUi(true);
        updateRunProgress(payload);
        pollTimer = window.setTimeout(pollActiveRun, 400);
      }
      if (revision !== assetOpenRevision || activeRunId !== normalized) return;
      await loadAssets();
    } catch (error) {
      if (revision !== assetOpenRevision || activeRunId !== normalized) return;
      setRunningUi(false);
      setStatus(error && error.message ? error.message : "测评资产打开失败。", "error");
    }
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

  function detachActiveAudit() {
    assetOpenRevision += 1;
    stopPolling();
    activeRunFailed = false;
    rememberActiveRun("");
    syncAssetUrl("");
    latestPayload = null;
    els.result.classList.add("hidden");
    els.loading.classList.add("hidden");
    els.batchProgress.style.width = "0%";
    setRunningUi(false);
  }

  async function deleteAsset(asset, button) {
    const runId = String(asset && asset.run_id || "");
    if (!runId) return;
    const scriptTitle = text(asset.script_title, "未命名剧本");
    if (!window.confirm(`确定删除《${scriptTitle}》的评分记录吗？此操作不可撤销。`)) return;
    button.disabled = true;
    const previousLabel = button.textContent;
    button.textContent = "删除中…";
    try {
      await requestApi(`/api/script-audit/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
      if (activeRunId === runId) detachActiveAudit();
      setStatus(`已删除《${scriptTitle}》的评分记录。`, "success");
      await loadAssets();
    } catch (error) {
      button.disabled = false;
      button.textContent = previousLabel;
      setStatus(error && error.message ? error.message : "评分记录删除失败。", "error");
    }
  }

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
    const pollingRunId = activeRunId;
    try {
      const payload = await requestApi(`/api/script-audit/runs/${encodeURIComponent(pollingRunId)}?recover=1`);
      if (activeRunId !== pollingRunId) return;
      if (payload.status === "succeeded") {
        activeRunFailed = false;
        renderResult(payload);
        setStatus("检测完成，已生成全剧心电图和逐集评分报告。", "success");
        syncAssetUrl(activeRunId);
        setRunningUi(false);
        loadAssets();
        return;
      }
      if (payload.status === "failed") {
        activeRunFailed = true;
        updateRunProgress(payload);
        const debugHint = payload.debug_file ? ` 调试记录：${payload.debug_file}` : "";
        setStatus(`${payload.error || "当前批次审核失败，可以点击继续检测从失败批次重试。"}${debugHint}`, "error");
        setRunningUi(false);
        loadAssets();
        return;
      }
      activeRunFailed = false;
      setRunningUi(true);
      updateRunProgress(payload);
      pollTimer = window.setTimeout(pollActiveRun, 1800);
    } catch (error) {
      if (activeRunId !== pollingRunId) return;
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
      syncAssetUrl(payload.run_id);
      activeRunFailed = false;
      els.title.value = payload.script_title || els.title.value;
      els.text.value = payload.script_text || scriptText;
      els.count.textContent = `${els.text.value.length} / 300000 字符`;
      if (payload.asset_reused && payload.status === "succeeded") {
        setRunningUi(false);
        renderResult(payload);
        setStatus("已找到同一剧本的历史评分，直接打开结果，没有重复消耗 Token。", "success");
        await loadAssets();
        return;
      }
      updateRunProgress(payload);
      await loadAssets();
      await pollActiveRun();
    } catch (error) {
      setRunningUi(false);
      setStatus(error && error.message ? error.message : "检测失败，请稍后重试。", "error");
    }
  }

  els.text.addEventListener("input", () => {
    els.count.textContent = `${els.text.value.length} / 300000 字符`;
    if (activeRunId) detachActiveAudit();
  });
  els.file.addEventListener("change", async () => {
    const file = els.file.files && els.file.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { setStatus("文件超过 10MB，请改为精简后的文本。", "error"); return; }
    detachActiveAudit();
    try {
      setStatus(`正在解析 ${file.name}…`);
      const form = new FormData();
      form.append("file", file);
      const payload = await requestApi("/api/script-audit/extract-file", { method: "POST", body: form });
      els.text.value = payload.script_text || "";
      els.title.value = payload.script_title || file.name.replace(/\.[^.]+$/, "");
      els.text.dispatchEvent(new Event("input"));
      setStatus(`已导入 ${file.name}，已切换到新剧本。`, "success");
      await loadAssets();
    } catch (_) { setStatus("文件读取失败，请改为粘贴文本。", "error"); }
  });
  els.run.addEventListener("click", runAudit);
  if (els.assetsRefresh) els.assetsRefresh.addEventListener("click", loadAssets);
  els.downloadText.addEventListener("click", () => {
    if (latestPayload) download((latestPayload.view && latestPayload.view.export_text) || "", "text/plain;charset=utf-8", safeFilename("txt"));
  });
  els.downloadJson.addEventListener("click", () => {
    if (latestPayload) download(JSON.stringify(latestPayload.audit, null, 2), "application/json;charset=utf-8", safeFilename("json"));
  });
  try { activeRunId = requestedAssetId() || window.localStorage.getItem(ACTIVE_RUN_KEY) || ""; } catch (_) { activeRunId = requestedAssetId(); }
  loadAssets();
  if (activeRunId) {
    openAsset(activeRunId, { recover: true });
  }
})();
