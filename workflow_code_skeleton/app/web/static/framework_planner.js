(function () {
  const config = window.frameworkPlannerConfig || {};
  const STORAGE_KEY = config.storageKey || "frameworkPlannerState.v2";
  const LEGACY_STORAGE_KEY = "new_stage_maker_framework_planner_v2";
  const API_BASE = config.apiBase || "/api/framework-planner";
  const authToken = String(config.authToken || "").trim();

  const VIEW_DEFS = [
    { id: "basic", label: "1. 基础配置", stageKey: "basic" },
    { id: "worldview", label: "2. 世界观方案", stageKey: "worldview" },
    { id: "character", label: "3. 人设方案", stageKey: "character" },
    { id: "beat_timeline", label: "4. 三幕十五节拍卡点规划时间轴", stageKey: "beat" },
    { id: "beat_explanation", label: "5. 三幕十五节拍卡点说明", stageKey: "beat" },
    { id: "storylines", label: "6. 不同人物故事线", stageKey: "storylines" },
    { id: "storyline_details", label: "7. 查看详细不同人物故事线", stageKey: "storylines" },
    { id: "storyline_decisions", label: "8. 故事线处理", stageKey: "storylines" },
    { id: "guide", label: "9. 整体改编指引四项", stageKey: "guide" },
    { id: "package", label: "10. 最终 JSON 策划包输出", stageKey: "package" },
  ];

  const STAGE_SEQUENCE = ["basic", "worldview", "character", "beat", "storylines", "guide", "package"];
  const BEAT_NAMES = [
    "开场",
    "主体呈现",
    "铺垫",
    "推动催化剂",
    "争执",
    "第二幕衔接点",
    "B故事线",
    "游戏及斗争",
    "中点",
    "危险逼近",
    "一败涂地",
    "灵魂黑夜",
    "第三幕衔接点",
    "结局",
    "终场画面",
  ];
  const STORYLINE_DECISIONS = [
    ["keep", "保留"],
    ["simplify", "精简"],
    ["delete", "删除"],
  ];
  const app = document.getElementById("frameworkPlannerApp");

  const initialState = {
    current_view: "basic",
    basic_config: {
      project_title: "未命名框架策划",
      mode: "创作",
      source_text: "",
      source_title: "",
      target_format: "短剧",
      season_count: 1,
      episodes_per_season: 60,
      minutes_per_episode: 2,
      adaptation_direction: "请保持强钩子、强反转、强情绪推进，并优先服务后续正式剧本生成链路。",
      user_constraints: "",
      user_requirements: "",
    },
    source_brief: {},
    worldview_plan: {},
    character_plan: {},
    beat_checkpoint_timeline: [],
    checkpoint_explanation: {},
    character_storylines: [],
    storyline_decisions: [],
    adaptation_guide: {},
    user_edit_history: [],
    framework_plan_package: {},
    validation_report: {},
    framework_score_report: "",
    beat_revision_round: 0,
    display_texts: {},
    raw_stage_responses: {},
    feedback: {
      worldview: "",
      character: "",
      beat: "",
      storylines: "",
      guide: "",
      package: "",
    },
    editors: {
      worldview_plan: "",
      character_plan: "",
      beat_checkpoint_timeline: "",
      checkpoint_explanation: "",
      adaptation_guide: "",
    },
    stage_state: {
      basic: { status: "editing", confirmed: false, locked: false },
      worldview: { status: "locked", confirmed: false, locked: true },
      character: { status: "locked", confirmed: false, locked: true },
      beat: { status: "locked", confirmed: false, locked: true },
      storylines: { status: "locked", confirmed: false, locked: true },
      guide: { status: "locked", confirmed: false, locked: true },
      package: { status: "locked", confirmed: false, locked: true },
    },
  };

  let state = loadState();
  const ui = {
    toast: "",
    loading: {},
    stageErrors: {},
    modalStorylineId: null,
    editMode: {
      worldview: false,
      character: false,
      beatTimeline: false,
      beatExplanation: false,
      guide: false,
    },
  };

  const realApi = {
    async runStage(stage, payload) {
      const response = await fetch(`${API_BASE}/stage/${stage}`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        ok: false,
        stage,
        error: `阶段 ${stage} 返回了无法解析的响应`,
      }));
      if (!response.ok || !data.ok) {
        throw toStageError(data, stage, response.status);
      }
      return data;
    },
    async runBeatScore(payload) {
      const response = await fetch(`${API_BASE}/stage/04/score`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        ok: false,
        stage: "04",
        error: "评分接口返回了无法解析的响应",
      }));
      if (!response.ok || !data.ok) {
        throw toStageError(data, "04", response.status);
      }
      return data;
    },
  };

  const mockApi = {
    async runStage(stage, payload) {
      return buildMockStageResponse(stage, payload || {});
    },
    async runBeatScore(payload) {
      return buildMockScoreResponse(payload || {});
    },
  };

  const planningApi = {
    async runStage(stage, payload) {
      try {
        return await realApi.runStage(stage, payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runStage(stage, payload);
        }
        throw error;
      }
    },
    async runBeatScore(payload) {
      try {
        return await realApi.runBeatScore(payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runBeatScore(payload);
        }
        throw error;
      }
    },
  };

  function buildHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    return headers;
  }

  function toStageError(data, fallbackStage, status) {
    const error = new Error(data && data.error ? data.error : `阶段 ${fallbackStage} 执行失败`);
    error.stage = (data && data.stage) || fallbackStage;
    error.status = status || 500;
    error.detail = (data && data.detail) || {};
    return error;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function loadState() {
    const saved = readStorage(STORAGE_KEY) || readStorage(LEGACY_STORAGE_KEY);
    return normalizeState(saved);
  }

  function readStorage(key) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function normalizeState(saved) {
    const next = clone(initialState);
    if (!saved || typeof saved !== "object") return next;
    mergeInto(next, saved);
    next.basic_config = Object.assign(clone(initialState.basic_config), saved.basic_config || {});
    next.feedback = Object.assign(clone(initialState.feedback), saved.feedback || {});
    next.editors = Object.assign(clone(initialState.editors), saved.editors || {});
    next.stage_state = Object.assign(clone(initialState.stage_state), saved.stage_state || {});
    STAGE_SEQUENCE.forEach((stageKey) => {
      next.stage_state[stageKey] = Object.assign(clone(initialState.stage_state[stageKey]), next.stage_state[stageKey] || {});
    });
    syncStorylineDecisions(next);
    if (!VIEW_DEFS.some((item) => item.id === next.current_view)) {
      next.current_view = "basic";
    }
    return next;
  }

  function mergeInto(target, source) {
    Object.keys(source || {}).forEach((key) => {
      const sourceValue = source[key];
      if (Array.isArray(sourceValue)) {
        target[key] = clone(sourceValue);
        return;
      }
      if (sourceValue && typeof sourceValue === "object") {
        if (!target[key] || typeof target[key] !== "object" || Array.isArray(target[key])) {
          target[key] = {};
        }
        mergeInto(target[key], sourceValue);
        return;
      }
      target[key] = sourceValue;
    });
  }

  function saveState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      // ignore storage write errors
    }
  }

  function showToast(message) {
    ui.toast = message;
    render();
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      ui.toast = "";
      render();
    }, 2400);
  }

  function recordHistory(action, detail) {
    state.user_edit_history.push({
      at: new Date().toISOString(),
      action,
      detail: detail || {},
    });
    if (state.user_edit_history.length > 200) {
      state.user_edit_history = state.user_edit_history.slice(-200);
    }
  }

  function viewDef(viewId) {
    return VIEW_DEFS.find((item) => item.id === viewId) || VIEW_DEFS[0];
  }

  function stageKeyForView(viewId) {
    return viewDef(viewId).stageKey;
  }

  function stageNoForKey(stageKey) {
    return {
      basic: "01",
      worldview: "02",
      character: "03",
      beat: "04",
      storylines: "05",
      guide: "06",
      package: "07",
    }[stageKey] || "";
  }

  function viewUnlocked(viewId) {
    const stageKey = stageKeyForView(viewId);
    if (stageKey === "basic") return true;
    if (stageKey === "worldview") return state.stage_state.basic.confirmed;
    if (stageKey === "character") return state.stage_state.worldview.confirmed;
    if (stageKey === "beat") return state.stage_state.character.confirmed;
    if (stageKey === "storylines") return state.stage_state.beat.confirmed;
    if (stageKey === "guide") return state.stage_state.storylines.confirmed;
    if (stageKey === "package") return state.stage_state.guide.confirmed;
    return false;
  }

  function setCurrentView(viewId) {
    if (!viewUnlocked(viewId)) {
      showToast("请先确认上游阶段");
      return;
    }
    state.current_view = viewId;
    render();
  }

  function setStageLoading(stageKey, loading) {
    ui.loading[stageKey] = Boolean(loading);
  }

  function isStageLoading(stageKey) {
    return Boolean(ui.loading[stageKey]);
  }

  function stageStatusTag(stageKey) {
    const stage = state.stage_state[stageKey];
    if (!stage) return `<span class="fp-tag">未知</span>`;
    if (stage.confirmed) return `<span class="fp-tag ok">已确认并锁定</span>`;
    if (stage.locked) return `<span class="fp-tag lock">待上游确认</span>`;
    if (stage.status === "running") return `<span class="fp-tag blue">处理中</span>`;
    if (stage.status === "generated") return `<span class="fp-tag blue">已生成，待确认</span>`;
    if (stage.status === "updated") return `<span class="fp-tag warn">已更新，待确认</span>`;
    if (stage.status === "error") return `<span class="fp-tag red">执行异常</span>`;
    if (stageKey === "basic") return `<span class="fp-tag blue">可编辑</span>`;
    return `<span class="fp-tag">待生成</span>`;
  }

  function unlockStage(stageKey) {
    if (!state.stage_state[stageKey]) return;
    state.stage_state[stageKey].locked = false;
    if (state.stage_state[stageKey].status === "locked") {
      state.stage_state[stageKey].status = "idle";
    }
  }

  function clearStageData(stageKey) {
    if (stageKey === "worldview") state.worldview_plan = {};
    if (stageKey === "character") state.character_plan = {};
    if (stageKey === "beat") {
      state.beat_checkpoint_timeline = [];
      state.checkpoint_explanation = {};
      state.framework_score_report = "";
      state.beat_revision_round = 0;
    }
    if (stageKey === "storylines") {
      state.character_storylines = [];
      state.storyline_decisions = [];
    }
    if (stageKey === "guide") state.adaptation_guide = {};
    if (stageKey === "package") {
      state.framework_plan_package = {};
      state.validation_report = {};
    }
    if (stageKey === "basic") {
      state.source_brief = {};
    }
  }

  function hasStageData(stageKey) {
    if (stageKey === "basic") return true;
    if (stageKey === "worldview") return !isEmptyValue(state.worldview_plan);
    if (stageKey === "character") return !isEmptyValue(state.character_plan);
    if (stageKey === "beat") return Array.isArray(state.beat_checkpoint_timeline) && state.beat_checkpoint_timeline.length > 0;
    if (stageKey === "storylines") return Array.isArray(state.character_storylines) && state.character_storylines.length > 0;
    if (stageKey === "guide") return !isEmptyValue(state.adaptation_guide);
    if (stageKey === "package") return !isEmptyValue(state.framework_plan_package);
    return false;
  }

  function downstreamStages(stageKey) {
    const index = STAGE_SEQUENCE.indexOf(stageKey);
    return index === -1 ? [] : STAGE_SEQUENCE.slice(index + 1);
  }

  function firstViewForStage(stageKey) {
    const item = VIEW_DEFS.find((view) => view.stageKey === stageKey);
    return item ? item.id : "basic";
  }

  function rollbackStage(stageKey) {
    const title = viewDef(firstViewForStage(stageKey)).label.replace(/^\d+\.\s*/, "");
    const proceed = window.confirm(`确认回退到“${title}”并清空下游结果与确认状态吗？`);
    if (!proceed) return;

    if (stageKey === "basic") {
      state.stage_state.basic.confirmed = false;
      state.stage_state.basic.locked = false;
      state.stage_state.basic.status = "editing";
      state.source_brief = {};
    } else {
      state.stage_state[stageKey].confirmed = false;
      state.stage_state[stageKey].locked = false;
      state.stage_state[stageKey].status = hasStageData(stageKey) ? "updated" : "idle";
    }

    downstreamStages(stageKey).forEach((downstreamKey) => {
      clearStageData(downstreamKey);
      state.stage_state[downstreamKey].confirmed = false;
      state.stage_state[downstreamKey].locked = true;
      state.stage_state[downstreamKey].status = "locked";
    });

    if (stageKey !== "package") {
      state.stage_state.package.locked = true;
      state.stage_state.package.status = "locked";
      state.stage_state.package.confirmed = false;
      state.framework_plan_package = {};
      state.validation_report = {};
    }

    ui.editMode.worldview = false;
    ui.editMode.character = false;
    ui.editMode.beatTimeline = false;
    ui.editMode.beatExplanation = false;
    ui.editMode.guide = false;
    state.current_view = firstViewForStage(stageKey);
    recordHistory("rollback", { stageKey });
    showToast("已回退并清空下游确认状态");
    render();
  }

  function isEmptyValue(value) {
    if (value == null) return true;
    if (typeof value === "string") return !value.trim();
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value).length === 0;
    return false;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatText(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }

  function prettyJson(value) {
    return JSON.stringify(value == null ? {} : value, null, 2);
  }

  function editorValueFor(key) {
    if (state.editors[key]) return state.editors[key];
    if (key === "worldview_plan") return prettyJson(state.worldview_plan);
    if (key === "character_plan") return prettyJson(state.character_plan);
    if (key === "beat_checkpoint_timeline") return prettyJson(state.beat_checkpoint_timeline);
    if (key === "checkpoint_explanation") return prettyJson(state.checkpoint_explanation);
    if (key === "adaptation_guide") return prettyJson(state.adaptation_guide);
    return "";
  }

  function parseEditorValue(editorKey, rawText) {
    const text = String(rawText || "").trim();
    if (!text) {
      if (editorKey === "beat_checkpoint_timeline") return [];
      return {};
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      if (editorKey === "adaptation_guide") {
        return {
          core_setting_adjustments: text,
          structure_and_rhythm: "",
          visualization_strategy: "",
          character_emotion_strategy: "",
        };
      }
      if (editorKey === "beat_checkpoint_timeline") {
        throw new Error("十五节拍时间轴必须是合法 JSON 数组");
      }
      if (editorKey === "checkpoint_explanation") {
        return {
          overview: text,
          beat_notes: [],
        };
      }
      return { content: text };
    }
  }

  function render() {
    saveState();
    app.innerHTML = `
      <div class="fp-shell">
        ${renderSidebar()}
        <main class="fp-main">
          ${renderTopbar()}
          ${renderCurrentView()}
        </main>
        ${renderFooter()}
        ${ui.toast ? `<div class="fp-toast">${escapeHtml(ui.toast)}</div>` : ""}
        ${ui.modalStorylineId ? renderStorylineModal(ui.modalStorylineId) : ""}
      </div>
    `;
  }

  function renderSidebar() {
    const navItems = VIEW_DEFS.map((item, index) => {
      const unlocked = viewUnlocked(item.id);
      const active = state.current_view === item.id ? "active" : "";
      const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? "done" : "";
      const locked = unlocked ? "" : "locked";
      const mark = done ? "✓" : String(index + 1);
      return `
        <button class="fp-nav-item ${active} ${done} ${locked}" data-action="go-view" data-view="${item.id}" ${unlocked ? "" : "disabled"}>
          <span>${escapeHtml(item.label)}</span>
          <span class="fp-nav-pill">${mark}</span>
        </button>
      `;
    }).join("");
    const modeLabel = config.backendReady ? "真实后端" : "Mock / 预留接口";
    const modeClass = config.backendReady ? "blue" : "warn";
    return `
      <aside class="fp-side">
        <div class="fp-logo">
          <div class="fp-logo-mark">FP</div>
          <div>
            剧本框架策划工作台
            <small>独立于主剧本生成链路</small>
          </div>
        </div>
        <div class="fp-side-note">
          <div class="fp-side-line"><span class="fp-tag ${modeClass}">${escapeHtml(modeLabel)}</span></div>
          <div>上游确认后锁定，进入下游后不可直接改动；如需修改，必须显式回退并清空下游确认状态。</div>
        </div>
        <div class="fp-side-note">
          <strong>本地保存：</strong>状态会自动写入 <code>${escapeHtml(STORAGE_KEY)}</code>，刷新页面后仍保留。
        </div>
        <nav class="fp-nav">${navItems}</nav>
      </aside>
    `;
  }

  function renderTopbar() {
    return `
      <div class="fp-top">
        <div>
          <div class="fp-kicker">Framework Planner / BETTER_FRAMEWORK_JSONS 01-07</div>
          <h1 class="fp-title">${escapeHtml(state.basic_config.project_title || "未命名框架策划")}</h1>
          <p class="fp-top-sub">04 阶段只维护一条 <code>beat_checkpoint_timeline</code>，<code>checkpoint_explanation</code> 只负责解释同一条时间轴。</p>
        </div>
        <div class="fp-top-actions">
          <a class="fp-btn small ghost" href="${escapeHtml(config.workspaceUrl || "/workspace")}">返回主工作台</a>
          <button class="fp-btn small" data-action="copy-working-payload">复制当前状态 JSON</button>
          <button class="fp-btn small danger" data-action="reset-state">重置本地状态</button>
        </div>
      </div>
      <div class="fp-card fp-steps">${renderStepRail()}</div>
    `;
  }

  function renderStepRail() {
    return VIEW_DEFS.map((item, index) => {
      const active = state.current_view === item.id ? "active" : "";
      const done = state.stage_state[item.stageKey] && state.stage_state[item.stageKey].confirmed ? "done" : "";
      const line = index < VIEW_DEFS.length - 1 ? `<span class="fp-step-line"></span>` : "";
      const mark = done ? "✓" : String(index + 1);
      return `<div class="fp-step ${active} ${done}"><span class="fp-step-dot">${mark}</span><span>${escapeHtml(item.label.replace(/^\d+\.\s*/, ""))}</span></div>${line}`;
    }).join("");
  }

  function renderCurrentView() {
    switch (state.current_view) {
      case "basic":
        return renderBasicView();
      case "worldview":
        return renderPlanStageView({
          stageKey: "worldview",
          title: "世界观方案",
          subtitle: "生成、编辑、更新、确认都在这里完成。只有基础配置确认并锁定后，世界观方案才可生成。",
          dataKey: "worldview_plan",
          nextTitle: "人设方案",
        });
      case "character":
        return renderPlanStageView({
          stageKey: "character",
          title: "人设方案",
          subtitle: "人设必须服从已确认世界观。确认后才解锁 04 阶段的三幕十五节拍卡点规划。",
          dataKey: "character_plan",
          nextTitle: "三幕十五节拍卡点规划",
        });
      case "beat_timeline":
        return renderBeatTimelineView();
      case "beat_explanation":
        return renderBeatExplanationView();
      case "storylines":
        return renderStorylinesView();
      case "storyline_details":
        return renderStorylineDetailsView();
      case "storyline_decisions":
        return renderStorylineDecisionView();
      case "guide":
        return renderGuideView();
      case "package":
        return renderPackageView();
      default:
        return renderBasicView();
    }
  }

  function renderBasicView() {
    const stage = state.stage_state.basic;
    const locked = stage.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">基础配置</h2>
            <p class="fp-card-sub">这里会同时准备 01 阶段所需输入。点击确认时，会先调用 <code>/api/framework-planner/stage/01</code> 提取 <code>source_brief</code>，成功后才正式锁定基础配置。</p>
          </div>
          ${stageStatusTag("basic")}
        </div>
        ${locked ? `<div class="fp-inline-warning">基础配置已确认并锁定。如需修改，请显式回退到该阶段，系统会清空下游确认状态。</div>` : ""}
        <div class="fp-grid two">
          <div class="fp-field">
            <label>项目标题</label>
            <input data-config-key="project_title" value="${escapeHtml(state.basic_config.project_title)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>写作模式</label>
            <select data-config-key="mode" ${locked ? "disabled" : ""}>
              <option value="创作" ${state.basic_config.mode === "创作" ? "selected" : ""}>创作</option>
              <option value="改写" ${state.basic_config.mode === "改写" ? "selected" : ""}>改写</option>
            </select>
          </div>
        </div>
        <div class="fp-grid two" style="margin-top:14px">
          <div class="fp-field">
            <label>作品标题 / source_title</label>
            <input data-config-key="source_title" placeholder="例如：机甲纪元，拳爆天星" value="${escapeHtml(state.basic_config.source_title)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>目标形式 / target_format</label>
            <input data-config-key="target_format" placeholder="例如：短剧、长剧、网文剧本" value="${escapeHtml(state.basic_config.target_format)}" ${locked ? "disabled" : ""} />
          </div>
        </div>
        <div class="fp-grid three" style="margin-top:14px">
          <div class="fp-field">
            <label>季数</label>
            <input type="number" min="1" data-config-key="season_count" value="${escapeHtml(state.basic_config.season_count)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>每季集数</label>
            <input type="number" min="15" data-config-key="episodes_per_season" value="${escapeHtml(state.basic_config.episodes_per_season)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>每集分钟数</label>
            <input type="number" min="1" data-config-key="minutes_per_episode" value="${escapeHtml(state.basic_config.minutes_per_episode)}" ${locked ? "disabled" : ""} />
          </div>
        </div>
        <div class="fp-field" style="margin-top:14px">
          <label>原文 / 故事材料 source_text</label>
          <textarea data-config-key="source_text" placeholder="可直接粘贴原文、梗概、旧策划、分集等材料。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.source_text)}</textarea>
        </div>
        <div class="fp-grid two" style="margin-top:14px">
          <div class="fp-field">
            <label>改编方向 adaptation_direction</label>
            <textarea data-config-key="adaptation_direction" placeholder="例如：压缩支线，强化中点反转，偏短剧强情绪推进。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.adaptation_direction)}</textarea>
          </div>
          <div class="fp-field">
            <label>用户要求 user_requirements</label>
            <textarea data-config-key="user_requirements" placeholder="补充平台风格、人物偏好、节奏要求等。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.user_requirements)}</textarea>
          </div>
        </div>
        <div class="fp-field" style="margin-top:14px">
          <label>限制条件 user_constraints</label>
          <textarea data-config-key="user_constraints" placeholder="例如：不能改世界观底层逻辑，不能删除某角色。" ${locked ? "disabled" : ""}>${escapeHtml(state.basic_config.user_constraints)}</textarea>
        </div>
        ${!isEmptyValue(state.source_brief) ? `
          <div class="fp-stage-note">
            <strong>01 阶段 source_brief 预览：</strong>
            <pre class="fp-json-inline">${escapeHtml(prettyJson(state.source_brief))}</pre>
          </div>
        ` : ""}
        <div class="fp-actions">
          ${locked ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="basic">回退到此阶段并清空下游</button>` : ""}
          <button class="fp-btn primary" data-action="confirm-basic" ${isStageLoading("basic") ? "disabled" : ""}>
            ${isStageLoading("basic") ? "正在提取原文信息..." : "确认基础配置并提取原文信息"}
          </button>
        </div>
      </section>
    `;
  }

  function renderPlanStageView(options) {
    const stage = state.stage_state[options.stageKey];
    const data = state[options.dataKey];
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    const editing = ui.editMode[options.stageKey];
    const feedback = state.feedback[options.stageKey] || "";
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">${escapeHtml(options.title)}</h2>
            <p class="fp-card-sub">${escapeHtml(options.subtitle)}</p>
          </div>
          ${stageStatusTag(options.stageKey)}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">${escapeHtml(options.title)}已确认并锁定。下游内容已基于当前版本生成，如需改动请显式回退。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认上游阶段。</div>` : editing ? renderEditorBlock(options.dataKey, options.title) : renderDataBlock(data)}
        ${renderStageError(options.stageKey)}
        ${!locked ? `
          <div class="fp-field" style="margin-top:14px">
            <label>用户修改意见 / AI 更新反馈</label>
            <textarea data-feedback-key="${options.stageKey}" placeholder="这里的内容会作为 user_feedback 传给后端 revise 接口。">${escapeHtml(feedback)}</textarea>
          </div>
        ` : ""}
        <div class="fp-lock-note">所有编辑必须先“更新”再“确认”。确认后解锁下游，并禁止继续直接修改上游。</div>
        <div class="fp-actions">
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="${options.stageKey}">回退到此阶段并清空下游</button>` : ""}
          ${editing ? `
            <button class="fp-btn" data-action="cancel-editor" data-editor-stage="${options.stageKey}">取消</button>
            <button class="fp-btn primary" data-action="save-editor" data-editor-key="${options.dataKey}" data-stage-key="${options.stageKey}">更新${escapeHtml(options.title)}</button>
          ` : `
            <button class="fp-btn" data-action="run-stage-generate" data-stage-key="${options.stageKey}" ${locked || confirmed || isStageLoading(options.stageKey) ? "disabled" : ""}>生成${escapeHtml(options.title)}</button>
            <button class="fp-btn" data-action="run-stage-revise" data-stage-key="${options.stageKey}" ${locked || confirmed || isStageLoading(options.stageKey) || isEmptyValue(data) ? "disabled" : ""}>基于意见更新</button>
            <button class="fp-btn" data-action="open-editor" data-editor-stage="${options.stageKey}" data-editor-key="${options.dataKey}" ${locked || confirmed || isEmptyValue(data) ? "disabled" : ""}>编辑</button>
            <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="${options.stageKey}" ${locked || confirmed || isEmptyValue(data) ? "disabled" : ""}>确认并进入${escapeHtml(options.nextTitle)}</button>
          `}
        </div>
      </section>
    `;
  }

  function renderBeatTimelineView() {
    const stage = state.stage_state.beat;
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    const editing = ui.editMode.beatTimeline;
    const canConfirm = state.beat_checkpoint_timeline.length === 15 && !isEmptyValue(state.checkpoint_explanation);
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">三幕十五节拍卡点规划时间轴</h2>
            <p class="fp-card-sub">04 阶段只维护一条 <code>beat_checkpoint_timeline</code>。不要再额外造一套 <code>checkpointPlan</code>。</p>
          </div>
          ${stageStatusTag("beat")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">04 阶段已确认并锁定，05 人物故事线会严格基于这 15 个节拍继续拆解。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认人设方案。</div>` : editing ? renderEditorBlock("beat_checkpoint_timeline", "三幕十五节拍卡点时间轴") : renderBeatTimeline(state.beat_checkpoint_timeline)}
        ${renderStageError("beat")}
        ${!locked ? `
          <div class="fp-field" style="margin-top:14px">
            <label>04 用户反馈 / 修改意见</label>
            <textarea data-feedback-key="beat" placeholder="这里会作为 user_feedback 传给 04 revise；framework_score_report 会自动从评分接口读取。">${escapeHtml(state.feedback.beat || "")}</textarea>
          </div>
          ${state.framework_score_report ? `
            <div class="fp-stage-note">
              <strong>最近一次 framework_score_report：</strong>
              <pre class="fp-json-inline">${escapeHtml(state.framework_score_report)}</pre>
            </div>
          ` : ""}
        ` : ""}
        <div class="fp-lock-note">后续评分循环只通过 <code>framework_score_report</code> 这一个输入口回流给 04 阶段。</div>
        <div class="fp-actions">
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="beat">回退到此阶段并清空下游</button>` : ""}
          ${editing ? `
            <button class="fp-btn" data-action="cancel-editor" data-editor-stage="beatTimeline">取消</button>
            <button class="fp-btn primary" data-action="save-editor" data-editor-key="beat_checkpoint_timeline" data-stage-key="beat">更新时间轴</button>
          ` : `
            <button class="fp-btn" data-action="run-stage-generate" data-stage-key="beat" ${locked || confirmed || isStageLoading("beat") ? "disabled" : ""}>生成时间轴</button>
            <button class="fp-btn" data-action="run-stage-revise" data-stage-key="beat" ${locked || confirmed || isStageLoading("beat") || !state.beat_checkpoint_timeline.length ? "disabled" : ""}>基于意见更新</button>
            <button class="fp-btn" data-action="run-score-loop" ${locked || confirmed || isStageLoading("beat") ? "disabled" : ""}>运行评分循环（最多 3 轮）</button>
            <button class="fp-btn" data-action="open-editor" data-editor-stage="beatTimeline" data-editor-key="beat_checkpoint_timeline" ${locked || confirmed || !state.beat_checkpoint_timeline.length ? "disabled" : ""}>编辑时间轴</button>
            <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="beat" ${locked || confirmed || !canConfirm ? "disabled" : ""}>确认并进入人物故事线</button>
          `}
        </div>
      </section>
    `;
  }

  function renderBeatTimeline(items) {
    if (!Array.isArray(items) || !items.length) {
      return `<div class="fp-empty">尚未生成 04 阶段时间轴。确认 03 后，才能生成 15 条固定顺序的 beat_checkpoint_timeline。</div>`;
    }
    const nodes = items.map((item) => `
      <article class="fp-beat-node">
        <div class="fp-beat-act">${escapeHtml(item.act || "")}</div>
        <div class="fp-beat-title">${escapeHtml(`${item.beat_no}. ${item.beat_name}`)}</div>
        <div class="fp-beat-dot"></div>
        <div class="fp-beat-range">${escapeHtml(item.episode_range || "")}</div>
      </article>
    `).join("");
    const cards = items.map((item) => `
      <article class="fp-beat-card">
        <h3>${escapeHtml(`${item.beat_no}. ${item.beat_name}`)}</h3>
        <div class="fp-beat-meta">${escapeHtml(item.act || "")} · ${escapeHtml(item.episode_range || "")} · ${escapeHtml(item.checkpoint_title || "")}</div>
        <p><strong>叙事功能：</strong>${escapeHtml(item.narrative_function || "")}</p>
        <p><strong>剧情内容：</strong>${escapeHtml(item.plot_content || "")}</p>
        <p><strong>人物变化：</strong>${escapeHtml(item.character_change || "")}</p>
        <p><strong>冲突升级：</strong>${escapeHtml(item.conflict_upgrade || "")}</p>
        <p><strong>钩子 / 反转：</strong>${escapeHtml(item.hook_or_reversal || "")}</p>
        <p><strong>关联故事线：</strong>${escapeHtml((item.linked_storylines || []).join("、"))}</p>
      </article>
    `).join("");
    return `
      <div class="fp-timeline-wrap"><div class="fp-timeline">${nodes}</div></div>
      <div class="fp-json-meta">当前共 ${items.length} 条节拍，确认按钮要求固定为 15 条。</div>
      <div class="fp-beat-card-grid">${cards}</div>
    `;
  }

  function renderBeatExplanationView() {
    const stage = state.stage_state.beat;
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    const editing = ui.editMode.beatExplanation;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">三幕十五节拍卡点说明</h2>
            <p class="fp-card-sub"><code>checkpoint_explanation</code> 只解释同一条 beat 时间轴，不再复制第二套卡点结构。</p>
          </div>
          ${stageStatusTag("beat")}
        </div>
        ${locked ? `<div class="fp-empty">请先确认人设方案。</div>` : editing ? renderEditorBlock("checkpoint_explanation", "卡点说明") : renderDataBlock(state.checkpoint_explanation)}
        <div class="fp-actions">
          ${editing ? `
            <button class="fp-btn" data-action="cancel-editor" data-editor-stage="beatExplanation">取消</button>
            <button class="fp-btn primary" data-action="save-editor" data-editor-key="checkpoint_explanation" data-stage-key="beat">更新卡点说明</button>
          ` : `
            <button class="fp-btn" data-action="open-editor" data-editor-stage="beatExplanation" data-editor-key="checkpoint_explanation" ${locked || confirmed || isEmptyValue(state.checkpoint_explanation) ? "disabled" : ""}>编辑说明</button>
            <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="beat" ${locked || confirmed || state.beat_checkpoint_timeline.length !== 15 || isEmptyValue(state.checkpoint_explanation) ? "disabled" : ""}>确认 04 并进入人物故事线</button>
          `}
        </div>
      </section>
    `;
  }

  function renderStorylinesView() {
    const stage = state.stage_state.storylines;
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">不同人物故事线</h2>
            <p class="fp-card-sub">05 阶段负责生成 <code>character_storylines</code>。故事线详情与处理决策分别放在后两个视图中查看和修改。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">人物故事线已确认并锁定。06 阶段的整体改编指引会以当前故事线取舍为准。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineCards(state.character_storylines, { concise: true })}
        ${renderStageError("storylines")}
        ${!locked ? `
          <div class="fp-field" style="margin-top:14px">
            <label>05 用户反馈 / 修改意见</label>
            <textarea data-feedback-key="storylines" placeholder="会作为 user_feedback 传入 stage 05 revise。">${escapeHtml(state.feedback.storylines || "")}</textarea>
          </div>
        ` : ""}
        <div class="fp-lock-note">故事线处理支持 keep / simplify / delete。只有先更新，再确认，06 才会解锁。</div>
        <div class="fp-actions">
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="storylines">回退到此阶段并清空下游</button>` : ""}
          <button class="fp-btn" data-action="run-stage-generate" data-stage-key="storylines" ${locked || confirmed || isStageLoading("storylines") ? "disabled" : ""}>生成人物故事线</button>
          <button class="fp-btn" data-action="run-stage-revise" data-stage-key="storylines" ${locked || confirmed || isStageLoading("storylines") || !state.character_storylines.length ? "disabled" : ""}>基于意见更新</button>
          <button class="fp-btn" data-action="go-view" data-view="storyline_details" ${locked || !state.character_storylines.length ? "disabled" : ""}>查看详细故事线</button>
          <button class="fp-btn primary" data-action="go-view" data-view="storyline_decisions" ${locked || !state.character_storylines.length ? "disabled" : ""}>进入故事线处理</button>
        </div>
      </section>
    `;
  }

  function renderStorylineDetailsView() {
    const stage = state.stage_state.storylines;
    const locked = stage.locked;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">查看详细不同人物故事线</h2>
            <p class="fp-card-sub">这里必须能看到 <code>detailed_storyline</code>、<code>linked_beats</code>、<code>episode_distribution</code>、<code>edit_notes</code>。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${locked ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineCards(state.character_storylines, { detailed: true })}
        <div class="fp-actions">
          <button class="fp-btn" data-action="go-view" data-view="storylines" ${locked ? "disabled" : ""}>返回故事线总览</button>
          <button class="fp-btn primary" data-action="go-view" data-view="storyline_decisions" ${locked || !state.character_storylines.length ? "disabled" : ""}>去处理保留 / 精简 / 删除</button>
        </div>
      </section>
    `;
  }

  function renderStorylineDecisionView() {
    const stage = state.stage_state.storylines;
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    const canConfirm = state.character_storylines.length > 0;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">故事线处理：保留 / 精简 / 删除</h2>
            <p class="fp-card-sub">这里统一修改 <code>storyline_decisions</code>，并回写到每条故事线的 <code>decision</code> 字段。</p>
          </div>
          ${stageStatusTag("storylines")}
        </div>
        ${locked ? `<div class="fp-empty">请先确认 04 阶段。</div>` : renderStorylineDecisionGrid()}
        <div class="fp-actions">
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="storylines">回退到此阶段并清空下游</button>` : ""}
          <button class="fp-btn" data-action="go-view" data-view="storyline_details" ${locked ? "disabled" : ""}>返回详情查看</button>
          <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="storylines" ${locked || confirmed || !canConfirm ? "disabled" : ""}>确认并进入整体改编指引</button>
        </div>
      </section>
    `;
  }

  function renderGuideView() {
    const stage = state.stage_state.guide;
    const locked = stage.locked;
    const confirmed = stage.confirmed;
    const editing = ui.editMode.guide;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">整体改编指引四项</h2>
            <p class="fp-card-sub">06 阶段建议输出四个稳定字段：<code>core_setting_adjustments</code>、<code>structure_and_rhythm</code>、<code>visualization_strategy</code>、<code>character_emotion_strategy</code>。</p>
          </div>
          ${stageStatusTag("guide")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">整体改编指引已确认并锁定。现在可以生成最终 JSON 策划包。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认 05 阶段。</div>` : editing ? renderEditorBlock("adaptation_guide", "整体改编指引") : renderGuideCards(state.adaptation_guide)}
        ${renderStageError("guide")}
        ${!locked ? `
          <div class="fp-field" style="margin-top:14px">
            <label>06 用户反馈 / 修改意见</label>
            <textarea data-feedback-key="guide" placeholder="会作为 user_feedback 传入 stage 06 revise。">${escapeHtml(state.feedback.guide || "")}</textarea>
          </div>
        ` : ""}
        <div class="fp-actions">
          ${confirmed ? `<button class="fp-btn danger" data-action="rollback-stage" data-stage-key="guide">回退到此阶段并清空下游</button>` : ""}
          ${editing ? `
            <button class="fp-btn" data-action="cancel-editor" data-editor-stage="guide">取消</button>
            <button class="fp-btn primary" data-action="save-editor" data-editor-key="adaptation_guide" data-stage-key="guide">更新改编指引</button>
          ` : `
            <button class="fp-btn" data-action="run-stage-generate" data-stage-key="guide" ${locked || confirmed || isStageLoading("guide") ? "disabled" : ""}>生成改编指引</button>
            <button class="fp-btn" data-action="run-stage-revise" data-stage-key="guide" ${locked || confirmed || isStageLoading("guide") || isEmptyValue(state.adaptation_guide) ? "disabled" : ""}>基于意见更新</button>
            <button class="fp-btn" data-action="open-editor" data-editor-stage="guide" data-editor-key="adaptation_guide" ${locked || confirmed || isEmptyValue(state.adaptation_guide) ? "disabled" : ""}>编辑</button>
            <button class="fp-btn primary" data-action="confirm-stage" data-stage-key="guide" ${locked || confirmed || isEmptyValue(state.adaptation_guide) ? "disabled" : ""}>确认并进入最终 JSON 输出</button>
          `}
        </div>
      </section>
    `;
  }

  function renderPackageView() {
    const locked = state.stage_state.package.locked;
    const hasOutput = !isEmptyValue(state.framework_plan_package);
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">最终 JSON 策划包输出</h2>
            <p class="fp-card-sub">这里展示的最终内容必须来自 07 阶段返回的 <code>framework_plan_package</code> 和 <code>validation_report</code>，而不是前端自行拼接的 mock 数据。</p>
          </div>
          ${locked ? `<span class="fp-tag lock">待上游确认</span>` : hasOutput ? `<span class="fp-tag ok">07 输出已生成</span>` : `<span class="fp-tag blue">等待生成</span>`}
        </div>
        ${locked ? `<div class="fp-empty">请先确认 06 阶段。</div>` : `
          <div class="fp-field" style="margin-bottom:14px">
            <label>07 用户反馈 / 修改意见</label>
            <textarea data-feedback-key="package" placeholder="会作为 user_feedback 传入 stage 07 revise。">${escapeHtml(state.feedback.package || "")}</textarea>
          </div>
          ${renderPackageBlocks()}
        `}
        <div class="fp-actions">
          <button class="fp-btn" data-action="run-stage-generate" data-stage-key="package" ${locked || isStageLoading("package") ? "disabled" : ""}>生成最终策划包</button>
          <button class="fp-btn" data-action="run-stage-revise" data-stage-key="package" ${locked || isStageLoading("package") || !hasOutput ? "disabled" : ""}>基于意见重新校验</button>
          <button class="fp-btn primary" data-action="copy-final-package" ${locked || !hasOutput ? "disabled" : ""}>复制 07 输出 JSON</button>
        </div>
      </section>
    `;
  }

  function renderPackageBlocks() {
    if (isEmptyValue(state.framework_plan_package)) {
      return `<div class="fp-empty">07 阶段尚未执行。确认 06 后，再生成最终 JSON 策划包。</div>`;
    }
    return `
      <div class="fp-grid two">
        <div class="fp-panel-card">
          <h3 class="fp-panel-title">framework_plan_package</h3>
          <pre class="fp-json">${escapeHtml(prettyJson(state.framework_plan_package))}</pre>
        </div>
        <div class="fp-panel-card">
          <h3 class="fp-panel-title">validation_report</h3>
          <pre class="fp-json">${escapeHtml(prettyJson(state.validation_report))}</pre>
        </div>
      </div>
      <div class="fp-stage-note">
        <strong>当前工作台 payload（用于 07 入参）：</strong>
        <pre class="fp-json-inline">${escapeHtml(prettyJson(buildWorkingPayload()))}</pre>
      </div>
    `;
  }

  function renderDataBlock(data) {
    if (isEmptyValue(data)) {
      return `<div class="fp-empty">当前阶段还没有可展示结果。请先生成，或基于上一版执行更新。</div>`;
    }
    return `<pre class="fp-json">${escapeHtml(prettyJson(data))}</pre>`;
  }

  function renderEditorBlock(editorKey, title) {
    return `
      <div class="fp-field fp-editor">
        <label>编辑${escapeHtml(title)}</label>
        <textarea data-editor-key="${editorKey}">${escapeHtml(editorValueFor(editorKey))}</textarea>
      </div>
    `;
  }

  function renderBeatNoteError(message) {
    return message ? `<div class="fp-inline-warning">${escapeHtml(message)}</div>` : "";
  }

  function renderStageError(stageKey) {
    const message = ui.stageErrors[stageKey];
    return renderBeatNoteError(message);
  }

  function renderStorylineCards(items, options) {
    if (!Array.isArray(items) || !items.length) {
      return `<div class="fp-empty">尚未生成人物故事线。</div>`;
    }
    return `<div class="fp-story-grid">${items.map((item) => {
      const distribution = (item.episode_distribution || []).map((segment) => `
        <div class="fp-detail-item">
          <strong>${escapeHtml(segment.episode_range || "未标注集数")}</strong>
          ${escapeHtml(segment.focus || "")}
        </div>
      `).join("");
      return `
        <article class="fp-story-card">
          <div class="fp-story-head">
            <h3>${escapeHtml(item.title || "")}</h3>
            <span class="fp-tag ${decisionTagClass(item.decision)}">${escapeHtml(decisionLabel(item.decision))}</span>
          </div>
          <p>${escapeHtml(item.summary || "")}</p>
          ${options && options.detailed ? `
            <div class="fp-detail-list">
              <div class="fp-detail-item"><strong>detailed_storyline</strong>${escapeHtml(item.detailed_storyline || "")}</div>
              <div class="fp-detail-item"><strong>linked_beats</strong>${escapeHtml((item.linked_beats || []).join(", "))}</div>
              <div class="fp-detail-item"><strong>edit_notes</strong>${escapeHtml(item.edit_notes || "")}</div>
            </div>
            ${distribution ? `<div class="fp-detail-list" style="margin-top:12px">${distribution}</div>` : ""}
          ` : ""}
          <div class="fp-actions" style="margin-top:12px">
            <button class="fp-btn small" data-action="open-storyline-modal" data-storyline-id="${escapeHtml(item.id)}">查看详细故事线</button>
            ${options && options.concise ? `<button class="fp-btn small" data-action="go-view" data-view="storyline_decisions">去做处理决策</button>` : ""}
          </div>
        </article>
      `;
    }).join("")}</div>`;
  }

  function renderStorylineDecisionGrid() {
    if (!Array.isArray(state.character_storylines) || !state.character_storylines.length) {
      return `<div class="fp-empty">尚未生成人物故事线。</div>`;
    }
    return `
      <div class="fp-story-grid">
        ${state.character_storylines.map((item) => `
          <article class="fp-story-card">
            <div class="fp-story-head">
              <h3>${escapeHtml(item.title || "")}</h3>
              <span class="fp-tag ${decisionTagClass(item.decision)}">${escapeHtml(decisionLabel(item.decision))}</span>
            </div>
            <p>${escapeHtml(item.summary || "")}</p>
            <div class="fp-radio-row">
              ${STORYLINE_DECISIONS.map(([value, label]) => `
                <label>
                  <input type="radio" name="storyline-${escapeHtml(item.id)}" data-action="change-storyline-decision" data-storyline-id="${escapeHtml(item.id)}" value="${value}" ${item.decision === value ? "checked" : ""} ${state.stage_state.storylines.confirmed ? "disabled" : ""} />
                  ${escapeHtml(label)}
                </label>
              `).join("")}
            </div>
            <div class="fp-actions" style="margin-top:0">
              <button class="fp-btn small" data-action="open-storyline-modal" data-storyline-id="${escapeHtml(item.id)}">查看并编辑细节</button>
            </div>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderStorylineModal(storylineId) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline) return "";
    return `
      <div class="fp-modal-mask" data-action="close-storyline-modal">
        <div class="fp-modal" data-modal-content="storyline">
          <div class="fp-modal-head">
            <div>
              <h2>${escapeHtml(storyline.title || "")}</h2>
              <p class="fp-modal-sub">支持查看并更新 <code>detailed_storyline</code>、<code>linked_beats</code>、<code>episode_distribution</code>、<code>edit_notes</code>。</p>
            </div>
            <button class="fp-btn small" data-action="close-storyline-modal">关闭</button>
          </div>
          <div class="fp-field">
            <label>summary</label>
            <textarea data-modal-field="summary">${escapeHtml(storyline.summary || "")}</textarea>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>detailed_storyline</label>
            <textarea data-modal-field="detailed_storyline">${escapeHtml(storyline.detailed_storyline || "")}</textarea>
          </div>
          <div class="fp-grid two" style="margin-top:12px">
            <div class="fp-field">
              <label>linked_beats（逗号分隔）</label>
              <input data-modal-field="linked_beats" value="${escapeHtml((storyline.linked_beats || []).join(", "))}" />
            </div>
            <div class="fp-field">
              <label>decision</label>
              <select data-modal-field="decision">
                ${STORYLINE_DECISIONS.map(([value, label]) => `<option value="${value}" ${storyline.decision === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>episode_distribution（JSON 数组）</label>
            <textarea data-modal-field="episode_distribution">${escapeHtml(prettyJson(storyline.episode_distribution || []))}</textarea>
          </div>
          <div class="fp-field" style="margin-top:12px">
            <label>edit_notes</label>
            <textarea data-modal-field="edit_notes">${escapeHtml(storyline.edit_notes || "")}</textarea>
          </div>
          <div class="fp-actions">
            <button class="fp-btn" data-action="close-storyline-modal">关闭</button>
            <button class="fp-btn primary" data-action="save-storyline-modal" data-storyline-id="${escapeHtml(storyline.id)}">更新故事线</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderGuideCards(data) {
    if (isEmptyValue(data)) {
      return `<div class="fp-empty">尚未生成整体改编指引。</div>`;
    }
    const cards = [
      ["core_setting_adjustments", "1. 核心设定调整"],
      ["structure_and_rhythm", "2. 叙事节奏与结构"],
      ["visualization_strategy", "3. 视觉化呈现"],
      ["character_emotion_strategy", "4. 角色与情绪塑造"],
    ];
    return `
      <div class="fp-guide-grid">
        ${cards.map(([key, label]) => `
          <article class="fp-guide-card">
            <h3>${escapeHtml(label)}</h3>
            <p>${escapeHtml((data && data[key]) || "")}</p>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderFooter() {
    const currentIndex = VIEW_DEFS.findIndex((item) => item.id === state.current_view);
    const previous = VIEW_DEFS[currentIndex - 1];
    const next = VIEW_DEFS[currentIndex + 1];
    return `
      <div class="fp-footer">
        <div class="fp-footer-note">localStorage 自动保存已开启。上游确认后不能直接改；如需修改，请使用显式回退。</div>
        <div class="fp-top-actions">
          <button class="fp-btn" data-action="go-view" data-view="${previous ? previous.id : ""}" ${previous ? "" : "disabled"}>上一步</button>
          <button class="fp-btn primary" data-action="go-view" data-view="${next ? next.id : ""}" ${next && viewUnlocked(next.id) ? "" : "disabled"}>下一步</button>
        </div>
      </div>
    `;
  }

  function decisionLabel(value) {
    return {
      keep: "保留",
      simplify: "精简",
      delete: "删除",
    }[value] || "保留";
  }

  function decisionTagClass(value) {
    return {
      keep: "blue",
      simplify: "warn",
      delete: "red",
    }[value] || "blue";
  }

  function buildWorkingPayload() {
    return {
      basic_config: clone(state.basic_config),
      source_brief: clone(state.source_brief),
      worldview_plan: clone(state.worldview_plan),
      character_plan: clone(state.character_plan),
      beat_checkpoint_timeline: clone(state.beat_checkpoint_timeline),
      checkpoint_explanation: clone(state.checkpoint_explanation),
      character_storylines: clone(state.character_storylines),
      storyline_decisions: clone(state.storyline_decisions),
      adaptation_guide: clone(state.adaptation_guide),
      user_edit_history: clone(state.user_edit_history),
      framework_plan_package: clone(state.framework_plan_package),
      validation_report: clone(state.validation_report),
      _meta: {
        framework_score_report: state.framework_score_report,
        beat_revision_round: state.beat_revision_round,
        stage_state: clone(state.stage_state),
      },
    };
  }

  function buildStagePayload(stageKey, options) {
    const revise = options && options.revise;
    if (stageKey === "basic") {
      return {
        mode: state.basic_config.mode,
        source_text: state.basic_config.source_text,
        source_title: state.basic_config.source_title || state.basic_config.project_title,
        target_format: state.basic_config.target_format,
        season_count: state.basic_config.season_count,
        episodes_per_season: state.basic_config.episodes_per_season,
        minutes_per_episode: state.basic_config.minutes_per_episode,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_constraints: state.basic_config.user_constraints,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "worldview") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        locked_basic_config: state.basic_config,
        basic_config: state.basic_config,
        previous_worldview_plan: revise ? state.worldview_plan : {},
        user_feedback: state.feedback.worldview,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "character") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        locked_basic_config: state.basic_config,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        previous_character_plan: revise ? state.character_plan : {},
        user_feedback: state.feedback.character,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "beat") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        previous_beat_checkpoint_timeline: revise ? state.beat_checkpoint_timeline : [],
        user_feedback: state.feedback.beat,
        framework_score_report: state.framework_score_report,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "storylines") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        previous_character_storylines: revise ? state.character_storylines : [],
        current_storyline_decisions: state.storyline_decisions,
        user_feedback: state.feedback.storylines,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "guide") {
      return {
        mode: revise ? "改写" : "创作",
        source_brief: state.source_brief,
        basic_config: state.basic_config,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        character_storylines: state.character_storylines,
        storyline_decisions: state.storyline_decisions,
        previous_adaptation_guide: revise ? state.adaptation_guide : {},
        user_feedback: state.feedback.guide,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    if (stageKey === "package") {
      return {
        mode: revise ? "改写" : "创作",
        basic_config: state.basic_config,
        source_brief: state.source_brief,
        worldview_plan: state.worldview_plan,
        character_plan: state.character_plan,
        beat_checkpoint_timeline: state.beat_checkpoint_timeline,
        checkpoint_explanation: state.checkpoint_explanation,
        character_storylines: state.character_storylines,
        storyline_decisions: state.storyline_decisions,
        adaptation_guide: state.adaptation_guide,
        user_edit_history: state.user_edit_history,
        previous_framework_plan_package: revise ? state.framework_plan_package : {},
        user_feedback: state.feedback.package,
        adaptation_direction: state.basic_config.adaptation_direction,
        user_requirements: state.basic_config.user_requirements,
      };
    }
    return {};
  }

  function applyStageResponse(stageNo, response) {
    state.raw_stage_responses[stageNo] = response.raw || {};
    state.display_texts[stageNo] = response.display_text || "";
    if (stageNo === "01") state.source_brief = response.data.source_brief || {};
    if (stageNo === "02") state.worldview_plan = response.data.worldview_plan || {};
    if (stageNo === "03") state.character_plan = response.data.character_plan || {};
    if (stageNo === "04") {
      state.beat_checkpoint_timeline = response.data.beat_checkpoint_timeline || [];
      state.checkpoint_explanation = response.data.checkpoint_explanation || {};
    }
    if (stageNo === "05") {
      state.character_storylines = response.data.character_storylines || [];
      syncStorylineDecisions(state);
    }
    if (stageNo === "06") state.adaptation_guide = response.data.adaptation_guide || {};
    if (stageNo === "07") {
      state.framework_plan_package = response.data.framework_plan_package || {};
      state.validation_report = response.data.validation_report || {};
    }
  }

  function syncStorylineDecisions(targetState) {
    const storylines = Array.isArray(targetState.character_storylines) ? targetState.character_storylines : [];
    targetState.storyline_decisions = storylines.map((item) => ({
      storyline_id: item.id,
      title: item.title,
      decision: item.decision || "keep",
    }));
  }

  async function runStage(stageKey, options) {
    const stageNo = stageNoForKey(stageKey);
    setStageLoading(stageKey, true);
    ui.stageErrors[stageKey] = "";
    state.stage_state[stageKey].status = "running";
    render();
    try {
      const response = await planningApi.runStage(stageNo, buildStagePayload(stageKey, options || {}));
      applyStageResponse(stageNo, response);
      state.stage_state[stageKey].status = options && options.revise ? "updated" : "generated";
      state.stage_state[stageKey].confirmed = false;
      recordHistory(options && options.revise ? "revise_stage" : "generate_stage", { stageKey, stageNo });
      return response;
    } catch (error) {
      state.stage_state[stageKey].status = "error";
      ui.stageErrors[stageKey] = formatStageError(error, stageNo);
      throw error;
    } finally {
      setStageLoading(stageKey, false);
      render();
    }
  }

  function formatStageError(error, stageNo) {
    const label = `阶段 ${stageNo}`;
    if (!error) return `${label} 执行失败`;
    const message = error.message || `${label} 执行失败`;
    if (/格式异常/.test(message)) return `${label} 返回格式异常，请重试或查看日志。`;
    return `${label}：${message}`;
  }

  async function confirmBasic() {
    if (!state.basic_config.source_title && !state.basic_config.project_title) {
      showToast("请至少填写作品标题或项目标题");
      return;
    }
    if (!state.basic_config.target_format) {
      showToast("请填写目标形式");
      return;
    }
    try {
      const response = await runStage("basic");
      state.stage_state.basic.confirmed = true;
      state.stage_state.basic.locked = true;
      state.stage_state.basic.status = "confirmed";
      unlockStage("worldview");
      state.current_view = "worldview";
      recordHistory("confirm_stage", { stageKey: "basic", stageNo: "01", sourceBrief: Boolean(response.data.source_brief) });
      showToast("基础配置已确认，并已生成 source_brief");
      render();
    } catch (error) {
      showToast(formatStageError(error, "01"));
    }
  }

  function confirmStage(stageKey) {
    if (stageKey === "worldview" && isEmptyValue(state.worldview_plan)) return;
    if (stageKey === "character" && isEmptyValue(state.character_plan)) return;
    if (stageKey === "beat" && (state.beat_checkpoint_timeline.length !== 15 || isEmptyValue(state.checkpoint_explanation))) {
      showToast("04 阶段必须同时具备 15 条时间轴和卡点说明后才能确认");
      return;
    }
    if (stageKey === "storylines" && !state.character_storylines.length) return;
    if (stageKey === "guide" && isEmptyValue(state.adaptation_guide)) return;

    state.stage_state[stageKey].confirmed = true;
    state.stage_state[stageKey].locked = true;
    state.stage_state[stageKey].status = "confirmed";
    if (stageKey === "worldview") {
      unlockStage("character");
      state.current_view = "character";
    }
    if (stageKey === "character") {
      unlockStage("beat");
      state.current_view = "beat_timeline";
    }
    if (stageKey === "beat") {
      unlockStage("storylines");
      state.current_view = "storylines";
    }
    if (stageKey === "storylines") {
      unlockStage("guide");
      state.current_view = "guide";
    }
    if (stageKey === "guide") {
      unlockStage("package");
      state.current_view = "package";
    }
    recordHistory("confirm_stage", { stageKey, stageNo: stageNoForKey(stageKey) });
    showToast("已确认并锁定，已解锁下游阶段");
    render();
  }

  function openEditor(editorStage, editorKey) {
    if (editorStage === "worldview") ui.editMode.worldview = true;
    if (editorStage === "character") ui.editMode.character = true;
    if (editorStage === "beatTimeline") ui.editMode.beatTimeline = true;
    if (editorStage === "beatExplanation") ui.editMode.beatExplanation = true;
    if (editorStage === "guide") ui.editMode.guide = true;
    state.editors[editorKey] = editorValueFor(editorKey);
    render();
  }

  function cancelEditor(editorStage) {
    if (editorStage === "worldview") ui.editMode.worldview = false;
    if (editorStage === "character") ui.editMode.character = false;
    if (editorStage === "beatTimeline") ui.editMode.beatTimeline = false;
    if (editorStage === "beatExplanation") ui.editMode.beatExplanation = false;
    if (editorStage === "guide") ui.editMode.guide = false;
    render();
  }

  function saveEditor(editorKey, stageKey) {
    try {
      const nextValue = parseEditorValue(editorKey, state.editors[editorKey]);
      if (editorKey === "worldview_plan") state.worldview_plan = nextValue;
      if (editorKey === "character_plan") state.character_plan = nextValue;
      if (editorKey === "beat_checkpoint_timeline") state.beat_checkpoint_timeline = Array.isArray(nextValue) ? nextValue : [];
      if (editorKey === "checkpoint_explanation") state.checkpoint_explanation = nextValue;
      if (editorKey === "adaptation_guide") state.adaptation_guide = nextValue;
      state.stage_state[stageKey].status = "updated";
      state.stage_state[stageKey].confirmed = false;
      if (stageKey === "worldview") ui.editMode.worldview = false;
      if (stageKey === "character") ui.editMode.character = false;
      if (editorKey === "beat_checkpoint_timeline") ui.editMode.beatTimeline = false;
      if (editorKey === "checkpoint_explanation") ui.editMode.beatExplanation = false;
      if (stageKey === "guide") ui.editMode.guide = false;
      recordHistory("save_editor", { stageKey, editorKey });
      showToast("已更新，确认后才会解锁下游");
      render();
    } catch (error) {
      showToast(error.message || "编辑内容格式不正确");
    }
  }

  function applyStorylineDecision(storylineId, decision) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline || state.stage_state.storylines.confirmed) return;
    storyline.decision = decision;
    syncStorylineDecisions(state);
    state.stage_state.storylines.status = "updated";
    state.stage_state.storylines.confirmed = false;
    recordHistory("storyline_decision", { storylineId, decision });
    saveState();
    render();
  }

  function openStorylineModal(storylineId) {
    ui.modalStorylineId = storylineId;
    render();
  }

  function closeStorylineModal() {
    ui.modalStorylineId = null;
    render();
  }

  function saveStorylineModal(storylineId) {
    const storyline = state.character_storylines.find((item) => item.id === storylineId);
    if (!storyline) return;
    const summary = document.querySelector('[data-modal-field="summary"]');
    const detailed = document.querySelector('[data-modal-field="detailed_storyline"]');
    const linkedBeats = document.querySelector('[data-modal-field="linked_beats"]');
    const episodeDistribution = document.querySelector('[data-modal-field="episode_distribution"]');
    const editNotes = document.querySelector('[data-modal-field="edit_notes"]');
    const decision = document.querySelector('[data-modal-field="decision"]');

    storyline.summary = summary ? summary.value.trim() : storyline.summary;
    storyline.detailed_storyline = detailed ? detailed.value.trim() : storyline.detailed_storyline;
    storyline.linked_beats = parseLinkedBeats(linkedBeats ? linkedBeats.value : "");
    storyline.edit_notes = editNotes ? editNotes.value.trim() : storyline.edit_notes;
    storyline.decision = decision ? decision.value : storyline.decision;
    if (episodeDistribution) {
      try {
        const parsed = JSON.parse(episodeDistribution.value || "[]");
        storyline.episode_distribution = Array.isArray(parsed) ? parsed : [];
      } catch (error) {
        showToast("episode_distribution 必须是合法 JSON 数组");
        return;
      }
    }
    syncStorylineDecisions(state);
    state.stage_state.storylines.status = "updated";
    state.stage_state.storylines.confirmed = false;
    recordHistory("update_storyline_detail", { storylineId });
    ui.modalStorylineId = null;
    showToast("故事线已更新，仍需确认");
    render();
  }

  function parseLinkedBeats(text) {
    return String(text || "")
      .split(",")
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item) && item > 0);
  }

  async function runBeatScoreLoop(maxRounds) {
    const rounds = Number(maxRounds || 3);
    let round = 1;
    let current = state.beat_checkpoint_timeline.length ? clone(state.beat_checkpoint_timeline) : null;
    let lastScoreReport = state.framework_score_report || "";

    setStageLoading("beat", true);
    ui.stageErrors.beat = "";
    state.stage_state.beat.status = "running";
    render();
    try {
      while (round <= rounds) {
        const payload = {
          mode: current ? "改写" : "创作",
          source_brief: state.source_brief,
          basic_config: state.basic_config,
          worldview_plan: state.worldview_plan,
          character_plan: state.character_plan,
          previous_beat_checkpoint_timeline: current || [],
          user_feedback: state.feedback.beat,
          framework_score_report: lastScoreReport,
          adaptation_direction: state.basic_config.adaptation_direction,
          user_requirements: state.basic_config.user_requirements,
        };
        const beatResponse = await planningApi.runStage("04", payload);
        applyStageResponse("04", beatResponse);
        state.beat_revision_round = round;
        state.stage_state.beat.status = "updated";
        state.stage_state.beat.confirmed = false;
        const scoreResponse = await planningApi.runBeatScore({
          beat_checkpoint_timeline: state.beat_checkpoint_timeline,
          checkpoint_explanation: state.checkpoint_explanation,
          basic_config: state.basic_config,
          source_brief: state.source_brief,
          worldview_plan: state.worldview_plan,
          character_plan: state.character_plan,
        });
        state.framework_score_report = ((scoreResponse.data || {}).framework_score_report) || "";
        state.raw_stage_responses["04_score"] = scoreResponse.raw || {};
        recordHistory("beat_score_round", { round, framework_score_report: state.framework_score_report });
        if (scoreLooksPassed(state.framework_score_report)) {
          showToast(`评分循环完成，第 ${round} 轮通过`);
          break;
        }
        current = clone(state.beat_checkpoint_timeline);
        lastScoreReport = state.framework_score_report;
        round += 1;
      }
      if (round > rounds && !scoreLooksPassed(state.framework_score_report)) {
        showToast(`评分循环已跑满 ${rounds} 轮，仍建议人工检查`);
      }
      render();
    } catch (error) {
      state.stage_state.beat.status = "error";
      ui.stageErrors.beat = formatStageError(error, "04");
      showToast(formatStageError(error, "04"));
      render();
    } finally {
      setStageLoading("beat", false);
      render();
    }
  }

  function scoreLooksPassed(report) {
    const text = String(report || "").toLowerCase();
    return /pass|通过|无需修改|可进入下一阶段/.test(text);
  }

  function resetState() {
    const proceed = window.confirm("确认重置当前框架策划工作台的本地状态吗？");
    if (!proceed) return;
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch (error) {
      // ignore
    }
    state = clone(initialState);
    ui.toast = "";
    ui.loading = {};
    ui.stageErrors = {};
    ui.modalStorylineId = null;
    ui.editMode = {
      worldview: false,
      character: false,
      beatTimeline: false,
      beatExplanation: false,
      guide: false,
    };
    render();
  }

  function copyText(text, successText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(successText || "已复制");
    }).catch(() => {
      showToast("复制失败，请检查浏览器权限");
    });
  }

  function buildMockStageResponse(stageNo, payload) {
    const response = {
      ok: true,
      stage: stageNo,
      data: {},
      raw: { mock: true, source: "frontend_fallback_mock" },
      display_text: "",
    };

    if (stageNo === "01") {
      response.data.source_brief = {
        source_title: payload.source_title || "未命名原作",
        target_format: payload.target_format || "短剧",
        core_premise: (payload.source_text || "").slice(0, 160) || "前端 mock 提取结果。",
        adaptation_direction: payload.adaptation_direction || "",
      };
      response.display_text = prettyJson(response.data.source_brief);
      return response;
    }
    if (stageNo === "02") {
      response.data.worldview_plan = {
        world_type: "前端 mock 世界观",
        main_conflict: "主角被迫进入高压规则体系并向上破局。",
      };
      response.display_text = prettyJson(response.data.worldview_plan);
      return response;
    }
    if (stageNo === "03") {
      response.data.character_plan = {
        protagonist: { name: "林渡", flaw: "过度逞强" },
        antagonist: { name: "周砺", role: "规则压迫者" },
      };
      response.display_text = prettyJson(response.data.character_plan);
      return response;
    }
    if (stageNo === "04") {
      const ranges = splitEpisodeRanges(Number((payload.basic_config || {}).episodes_per_season || 60));
      response.data.beat_checkpoint_timeline = BEAT_NAMES.map((name, index) => ({
        beat_no: index + 1,
        beat_name: name,
        act: index < 6 ? "第一幕" : index < 12 ? "第二幕" : "第三幕",
        episode_range: ranges[index],
        checkpoint_title: `${name}卡点`,
        narrative_function: `${name}叙事功能说明`,
        plot_content: `${name}剧情内容`,
        character_change: "主角状态发生递进变化",
        conflict_upgrade: "冲突继续升级",
        hook_or_reversal: `${name}结尾钩子`,
        linked_storylines: ["主角成长线"],
      }));
      response.data.checkpoint_explanation = {
        overview: "frontend mock checkpoint_explanation",
        beat_notes: response.data.beat_checkpoint_timeline.map((item) => ({
          beat_no: item.beat_no,
          explanation: item.plot_content,
        })),
      };
      response.display_text = prettyJson(response.data);
      return response;
    }
    if (stageNo === "05") {
      response.data.character_storylines = [
        {
          id: "protagonist_growth",
          title: "主角成长线",
          summary: "主角从被压制走向主动反攻。",
          detailed_storyline: "承担主线成长和策略升级。",
          linked_beats: [1, 4, 9, 12, 14, 15],
          episode_distribution: [{ episode_range: "前中后段", focus: "成长递进" }],
          edit_notes: "重点保留",
          decision: "keep",
        },
        {
          id: "b_story_relationship",
          title: "B故事情感线",
          summary: "承担关系变化和主题回流。",
          detailed_storyline: "帮助主角完成价值观转向。",
          linked_beats: [3, 7, 12, 15],
          episode_distribution: [{ episode_range: "中后段", focus: "关系升级" }],
          edit_notes: "建议精简",
          decision: "simplify",
        },
      ];
      response.display_text = prettyJson(response.data.character_storylines);
      return response;
    }
    if (stageNo === "06") {
      response.data.adaptation_guide = {
        core_setting_adjustments: "保留规则对抗骨架。",
        structure_and_rhythm: "保持强开局、中点反转、后段反攻。",
        visualization_strategy: "尽量用可拍摄冲突外化信息。",
        character_emotion_strategy: "强调主角由屈辱到反攻的情绪线。",
      };
      response.display_text = prettyJson(response.data.adaptation_guide);
      return response;
    }
    if (stageNo === "07") {
      response.data.framework_plan_package = buildWorkingPayload();
      response.data.validation_report = {
        passed: true,
        summary: "frontend mock 校验通过",
      };
      response.display_text = prettyJson(response.data);
      return response;
    }
    return response;
  }

  function buildMockScoreResponse(payload) {
    const beats = Array.isArray(payload.beat_checkpoint_timeline) ? payload.beat_checkpoint_timeline : [];
    const ok = beats.length === 15;
    const report = ok
      ? "PASS\n总评：frontend mock 认为 15 条节拍齐备，可进入下一阶段。"
      : `REVISE\n总评：当前仅有 ${beats.length} 条节拍，仍需补齐。`;
    return {
      ok: true,
      stage: "04",
      data: { framework_score_report: report },
      raw: { mock: true, source: "frontend_fallback_mock_score" },
      display_text: report,
    };
  }

  function splitEpisodeRanges(totalEpisodes) {
    const total = Math.max(15, Number(totalEpisodes) || 60);
    const weights = [3, 4, 4, 4, 4, 5, 5, 7, 5, 5, 4, 4, 3, 2, 1];
    const sum = weights.reduce((acc, item) => acc + item, 0);
    let start = 1;
    return weights.map((weight, index) => {
      const remaining = 15 - index;
      let length = index === weights.length - 1 ? total - start + 1 : Math.max(1, Math.round(total * weight / sum));
      if (start + length + remaining - 2 > total) {
        length = Math.max(1, total - start - remaining + 2);
      }
      const end = Math.min(total, start + length - 1);
      const text = start === end ? `第${start}集` : `第${start}-${end}集`;
      start = end + 1;
      return text;
    });
  }

  app.addEventListener("input", (event) => {
    const target = event.target;
    if (target.matches("[data-config-key]")) {
      const key = target.dataset.configKey;
      state.basic_config[key] = target.type === "number" ? Number(target.value) : target.value;
      saveState();
      return;
    }
    if (target.matches("[data-feedback-key]")) {
      state.feedback[target.dataset.feedbackKey] = target.value;
      saveState();
      return;
    }
    if (target.matches("[data-editor-key]")) {
      state.editors[target.dataset.editorKey] = target.value;
      return;
    }
  });

  app.addEventListener("click", async (event) => {
    const actionElement = event.target.closest("[data-action]");
    if (!actionElement) return;
    const action = actionElement.dataset.action;

    if (action === "go-view") {
      setCurrentView(actionElement.dataset.view);
      return;
    }
    if (action === "reset-state") {
      resetState();
      return;
    }
    if (action === "copy-working-payload") {
      copyText(prettyJson(buildWorkingPayload()), "已复制当前状态 JSON");
      return;
    }
    if (action === "copy-final-package") {
      copyText(prettyJson({
        framework_plan_package: state.framework_plan_package,
        validation_report: state.validation_report,
      }), "已复制 07 输出 JSON");
      return;
    }
    if (action === "confirm-basic") {
      await confirmBasic();
      return;
    }
    if (action === "run-stage-generate") {
      const stageKey = actionElement.dataset.stageKey;
      try {
        await runStage(stageKey, { revise: false });
        if (stageKey === "package") {
          showToast("已生成最终策划包");
        } else {
          showToast("已生成，若有人工修改请先更新再确认");
        }
      } catch (error) {
        showToast(formatStageError(error, stageNoForKey(stageKey)));
      }
      return;
    }
    if (action === "run-stage-revise") {
      const stageKey = actionElement.dataset.stageKey;
      try {
        await runStage(stageKey, { revise: true });
        showToast("已按修改意见更新，确认后才会解锁下游");
      } catch (error) {
        showToast(formatStageError(error, stageNoForKey(stageKey)));
      }
      return;
    }
    if (action === "confirm-stage") {
      confirmStage(actionElement.dataset.stageKey);
      return;
    }
    if (action === "rollback-stage") {
      rollbackStage(actionElement.dataset.stageKey);
      return;
    }
    if (action === "open-editor") {
      openEditor(actionElement.dataset.editorStage, actionElement.dataset.editorKey);
      return;
    }
    if (action === "cancel-editor") {
      cancelEditor(actionElement.dataset.editorStage);
      return;
    }
    if (action === "save-editor") {
      saveEditor(actionElement.dataset.editorKey, actionElement.dataset.stageKey);
      return;
    }
    if (action === "run-score-loop") {
      await runBeatScoreLoop(3);
      return;
    }
    if (action === "change-storyline-decision") {
      applyStorylineDecision(actionElement.dataset.storylineId, actionElement.value);
      return;
    }
    if (action === "open-storyline-modal") {
      openStorylineModal(actionElement.dataset.storylineId);
      return;
    }
    if (action === "close-storyline-modal") {
      if (!event.target.closest("[data-modal-content='storyline']") || event.target === actionElement) {
        closeStorylineModal();
      } else {
        closeStorylineModal();
      }
      return;
    }
    if (action === "save-storyline-modal") {
      saveStorylineModal(actionElement.dataset.storylineId);
      return;
    }
  });

  document.addEventListener("click", (event) => {
    if (event.target && event.target.matches(".fp-modal-mask[data-action='close-storyline-modal']")) {
      closeStorylineModal();
    }
  });

  window.frameworkPlannerDebug = {
    getState: () => clone(state),
    buildWorkingPayload,
    runBeatScoreLoop,
  };

  render();
})();
