(() => {
  const app = document.getElementById("framework-to-script-app");
  const params = new URLSearchParams(window.location.search);
  const sourceFrameworkProjectId = params.get("source_framework_project_id") || params.get("project_id") || "";
  const authToken = params.get("auth_token") || "";

  const state = {
    source: loadSource(),
    runningStage: "",
    error: "",
    sceneDictionary: null,
    scriptWorldRulesDigest: null,
    appearanceMapping: null,
    rawStage08: null,
    rawStage09: null,
  };

  hydrateFromSource();

  function loadSource() {
    try {
      const raw = window.localStorage.getItem("frameworkToScriptSource");
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function refreshSourceFromLocalStorage() {
    const latest = loadSource();
    state.source = Object.assign({}, state.source || {}, latest || {});
    hydrateFromSource();
  }

  function hydrateFromSource() {
    const source = state.source || {};
    state.sceneDictionary = source.sceneDictionary || source.scene_dictionary || state.sceneDictionary || null;
    state.scriptWorldRulesDigest = source.scriptWorldRulesDigest || source.script_world_rules_digest || state.scriptWorldRulesDigest || null;
    state.appearanceMapping = source.appearanceMapping || source.appearanceMapping || state.appearanceMapping || null;
  }

  function saveSourcePatch(patch) {
    state.source = Object.assign({}, state.source || {}, patch || {});
    hydrateFromSource();
    try {
      window.localStorage.setItem("frameworkToScriptSource", JSON.stringify(state.source));
    } catch (error) {}
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function prettyJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value ?? "");
    }
  }

  function apiUrl(path) {
    if (!authToken) return path;
    const url = new URL(path, window.location.origin);
    url.searchParams.set("auth_token", authToken);
    return url.pathname + url.search + url.hash;
  }

  function frameworkPackage() {
    return state.source.framework_plan_package || state.source.frameworkPlanPackage || {};
  }

  function characterPlan() {
    return state.source.character_plan || state.source.characterPlan || frameworkPackage().character_plan || frameworkPackage().characterPlan || {};
  }

  function beatTimeline() {
    return state.source.beat_checkpoint_timeline
      || state.source.beatCheckpointTimeline
      || frameworkPackage().beat_checkpoint_timeline
      || frameworkPackage().beatCheckpointTimeline
      || [];
  }

  function characterStorylines() {
    return state.source.character_storylines
      || state.source.characterStorylines
      || frameworkPackage().character_storylines
      || frameworkPackage().characterStorylines
      || [];
  }

  function worldviewPlan() {
    return state.source.worldview_plan
      || state.source.worldviewPlan
      || frameworkPackage().worldview_plan
      || frameworkPackage().worldviewPlan
      || {};
  }

  function hasObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
  }

  function hasFrameworkPackage() {
    return hasObject(frameworkPackage());
  }

  function canRunStage08() {
    refreshSourceFromLocalStorage();
    return hasFrameworkPackage() && !state.runningStage;
  }

  function canRunStage09() {
    refreshSourceFromLocalStorage();
    return hasFrameworkPackage()
      && hasObject(characterPlan())
      && hasObject(state.sceneDictionary)
      && !state.runningStage;
  }

  async function parseJsonResponse(response, label) {
    const rawText = await response.text();
    let data = {};
    try {
      data = rawText ? JSON.parse(rawText) : {};
    } catch (error) {
      throw new Error(`${label} 接口返回非 JSON：status=${response.status} body=${rawText.slice(0, 260).replace(/\s+/g, " ")}`);
    }
    if (!response.ok || data.ok === false || data.success === false) {
      throw new Error(data.error || data.message || data.fallback || `${label} 失败`);
    }
    return data;
  }

  async function runStage08() {
    refreshSourceFromLocalStorage();

    if (!hasFrameworkPackage()) {
      state.error = "缺少 framework_plan_package。请从 07 最终策划包页面重新进入。";
      render();
      return;
    }

    state.runningStage = "08";
    state.error = "";
    render();

    try {
      const payload = {
        source_framework_project_id: sourceFrameworkProjectId || state.source.source_framework_project_id || state.source.project_id || "",
        framework_plan_package: frameworkPackage(),
        worldview_plan: worldviewPlan(),
        beat_checkpoint_timeline: beatTimeline(),
        character_storylines: characterStorylines(),
      };

      const response = await fetch(apiUrl("/api/framework-to-script/stage/08"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await parseJsonResponse(response, "08 场景字典提炼");

      state.sceneDictionary = data.sceneDictionary;
      state.scriptWorldRulesDigest = data.scriptWorldRulesDigest;
      state.rawStage08 = data.raw_output || data;

      saveSourcePatch({
        sceneDictionary: data.sceneDictionary,
        scriptWorldRulesDigest: data.scriptWorldRulesDigest,
        stage08_saved_at: new Date().toISOString(),
      });
    } catch (error) {
      state.error = (error && error.message) || "08 场景字典提炼失败";
    } finally {
      state.runningStage = "";
      render();
    }
  }

  async function runStage09() {
    refreshSourceFromLocalStorage();

    if (!hasFrameworkPackage()) {
      state.error = "缺少 framework_plan_package。请从 07 最终策划包页面重新进入。";
      render();
      return;
    }
    if (!hasObject(state.sceneDictionary)) {
      state.error = "缺少 sceneDictionary。请先运行 08 场景字典提炼。";
      render();
      return;
    }
    if (!hasObject(characterPlan())) {
      state.error = "缺少 character_plan。请回到 07 框架资产检查人设方案是否已保存。";
      render();
      return;
    }

    state.runningStage = "09";
    state.error = "";
    render();

    try {
      const payload = {
        source_framework_project_id: sourceFrameworkProjectId || state.source.source_framework_project_id || state.source.project_id || "",
        framework_plan_package: frameworkPackage(),
        character_plan: characterPlan(),
        sceneDictionary: state.sceneDictionary,
        beat_checkpoint_timeline: beatTimeline(),
      };

      const response = await fetch(apiUrl("/api/framework-to-script/stage/09"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await parseJsonResponse(response, "09 人设服装 alias 映射");

      state.appearanceMapping = data.appearanceMapping;
      state.rawStage09 = data.raw_output || data;

      saveSourcePatch({
        appearanceMapping: data.appearanceMapping,
        stage09_saved_at: new Date().toISOString(),
      });
    } catch (error) {
      state.error = (error && error.message) || "09 人设服装 alias 映射失败";
    } finally {
      state.runningStage = "";
      render();
    }
  }

  function renderOutputBlock(title, value) {
    return `
      <details open class="wts-output">
        <summary>${escapeHtml(title)}</summary>
        <pre>${escapeHtml(prettyJson(value))}</pre>
      </details>
    `;
  }

  function renderStage08Card() {
    const done = hasObject(state.sceneDictionary) && hasObject(state.scriptWorldRulesDigest);
    const running = state.runningStage === "08";
    const disabled = running || !hasFrameworkPackage() || !!state.runningStage;

    return `
      <article class="wts-step ${done ? "done" : ""}">
        <b>08</b>
        <div>
          <div class="wts-step-head">
            <h3>场景字典提炼</h3>
            <span>${running ? "运行中" : done ? "已完成" : "待运行"}</span>
          </div>
          <p>输入：framework_plan_package.worldview_plan + beat_checkpoint_timeline + character_storylines</p>
          <p>输出：sceneDictionary + scriptWorldRulesDigest</p>
          <div class="wts-step-actions">
            <button type="button" ${disabled ? "disabled" : ""} data-action="run-stage-08">
              ${running ? "08 运行中..." : done ? "重新运行 08" : "运行 08"}
            </button>
          </div>
          ${done ? `
            ${renderOutputBlock("sceneDictionary", state.sceneDictionary)}
            ${renderOutputBlock("scriptWorldRulesDigest", state.scriptWorldRulesDigest)}
          ` : ""}
        </div>
      </article>
    `;
  }

  function renderStage09Card() {
    const done = hasObject(state.appearanceMapping);
    const running = state.runningStage === "09";
    const ready = hasObject(state.sceneDictionary) && hasObject(characterPlan());
    const disabled = running || !ready || !!state.runningStage;

    return `
      <article class="wts-step ${done ? "done" : ""} ${ready ? "" : "locked"}">
        <b>09</b>
        <div>
          <div class="wts-step-head">
            <h3>人设服装 alias 映射</h3>
            <span>${running ? "运行中" : done ? "已完成" : ready ? "待运行" : "等待 08"}</span>
          </div>
          <p>输入：character_plan + sceneDictionary + beat_checkpoint_timeline</p>
          <p>输出：appearanceMapping</p>
          <div class="wts-step-actions">
            <button type="button" ${disabled ? "disabled" : ""} data-action="run-stage-09">
              ${running ? "09 运行中..." : done ? "重新运行 09" : "运行 09"}
            </button>
          </div>
          ${!ready ? `<p class="wts-hint">请先完成 08，并确保框架资产里有人设方案 character_plan。</p>` : ""}
          ${done ? renderOutputBlock("appearanceMapping", state.appearanceMapping) : ""}
        </div>
      </article>
    `;
  }

  function renderPlaceholderStep(id, title, output, status = "待接入") {
    return `
      <article class="wts-step locked">
        <b>${escapeHtml(id)}</b>
        <div>
          <div class="wts-step-head">
            <h3>${escapeHtml(title)}</h3>
            <span>${escapeHtml(status)}</span>
          </div>
          <p>输出：${escapeHtml(output)}</p>
          <div class="wts-step-actions">
            <button disabled>查看输入</button>
            <button disabled>运行本阶段</button>
            <button disabled>查看输出</button>
          </div>
        </div>
      </article>
    `;
  }

  function render() {
    refreshSourceFromLocalStorage();

    const sourceId = sourceFrameworkProjectId || state.source.source_framework_project_id || state.source.project_id || "未指定";
    const sourceReady = hasFrameworkPackage();

    app.innerHTML = `
      <main class="wts-shell">
        <header class="wts-header">
          <div>
            <div class="wts-eyebrow">Framework to Script</div>
            <h1>框架转剧本工作台</h1>
            <p>这里不会自动后台生成。你可以从已保存的 07 最终策划包开始，逐步调试 08、09、10、因果冲突和正文对白融合。</p>
          </div>
          <div class="wts-actions">
            <a href="/framework-planner${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}">返回框架策划</a>
            <a href="/workspace${authToken ? `?auth_token=${encodeURIComponent(authToken)}` : ""}">返回主工作台</a>
          </div>
        </header>

        <section class="wts-card">
          <span>源框架资产</span>
          <strong>${escapeHtml(sourceId)}</strong>
          <p>${sourceReady ? "已读取 07 最终策划包，可以分步运行。" : "未读取到 07 最终策划包。请从框架策划 07 页面重新进入。"}</p>
          <div class="wts-step-actions">
            <button type="button" data-action="reload-source">重新读取框架上下文</button>
          </div>
        </section>

        ${state.error ? `<section class="wts-error">${escapeHtml(state.error)}</section>` : ""}

        <section class="wts-card">
          <h2>分步调试流程</h2>
          <div class="wts-steps">
            ${renderStage08Card()}
            ${renderStage09Card()}
            ${renderPlaceholderStep("10", "丰富分集计划", "allEnrichedEpisodePlan + allEnrichedEpisodePlanText", hasObject(state.appearanceMapping) ? "待接入" : "等待 09")}
            ${renderPlaceholderStep("11", "因果冲突推进计划", "batchCausalConflictPlan")}
            ${renderPlaceholderStep("12", "正文对白融合", "batchScriptText")}
          </div>
        </section>
      </main>
    `;
  }

  app.addEventListener("click", (event) => {
    const target = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!target) return;

    if (target.dataset.action === "reload-source") {
      event.preventDefault();
      refreshSourceFromLocalStorage();
      state.error = "";
      render();
    }

    if (target.dataset.action === "run-stage-08") {
      event.preventDefault();
      runStage08();
    }

    if (target.dataset.action === "run-stage-09") {
      event.preventDefault();
      runStage09();
    }
  });

  window.addEventListener("pageshow", () => {
    refreshSourceFromLocalStorage();
    render();
  });

  render();
})();
