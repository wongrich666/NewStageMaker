(function () {
  const STORAGE_KEY = "new_stage_maker_framework_planner_v2";

  const stepDefs = [
    ["basic", "基础配置"],
    ["worldview", "世界观方案"],
    ["characters", "人设方案"],
    ["beatPlan", "十五节拍卡点"],
    ["storylines", "人物故事线"],
    ["guide", "改编指引"],
    ["export", "JSON 输出"]
  ];

  const sectionOrder = ["basic", "worldview", "characters", "beatPlan", "storylines", "guide", "export"];

  const initialState = {
    currentStep: "basic",
    toast: "",
    modalLineId: null,
    exportVisible: true,
    configConfirmed: false,
    config: {
      projectTitle: "未命名框架策划",
      sourceType: "upload",
      fileName: "",
      seasonCount: 1,
      episodesPerSeason: 50,
      minutesPerEpisode: 2,
      targetGenre: "短剧",
      adaptationDirection: "请根据原小说内容进行短剧化框架策划，第一季内容控制在强钩子、强反转、强情绪推进内。",
      materialNote: ""
    },
    sections: {
      worldview: { status: "locked", confirmed: false, editing: false, text: "" },
      characters: { status: "locked", confirmed: false, editing: false, text: "" },
      beatPlan: { status: "locked", confirmed: false, items: [], explanation: "" },
      storylines: { status: "locked", confirmed: false, items: [] },
      guide: { status: "locked", confirmed: false, editing: false, items: [] }
    }
  };

  let state = loadState();
  let editBuffers = {};

  const app = document.getElementById("frameworkPlannerApp");

  function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return clone(initialState);
      return mergeState(clone(initialState), JSON.parse(raw));
    } catch (error) {
      return clone(initialState);
    }
  }

  function mergeState(base, saved) {
    const merged = Object.assign(base, saved || {});
    merged.config = Object.assign(base.config, (saved && saved.config) || {});
    merged.sections = Object.assign(base.sections, (saved && saved.sections) || {});
    Object.keys(base.sections).forEach((key) => {
      merged.sections[key] = Object.assign(base.sections[key], (saved && saved.sections && saved.sections[key]) || {});
    });
    return merged;
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatText(value) {
    return escapeHtml(value || "").replace(/\n/g, "<br>");
  }

  function showToast(message) {
    state.toast = message;
    render();
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      state.toast = "";
      render();
    }, 2200);
  }

  function stepIndex(id) {
    return stepDefs.findIndex(([key]) => key === id);
  }

  function isUnlocked(step) {
    if (step === "basic") return true;
    if (step === "worldview") return state.configConfirmed;
    if (step === "characters") return state.sections.worldview.confirmed;
    if (step === "beatPlan") return state.sections.characters.confirmed;
    if (step === "storylines") return state.sections.beatPlan.confirmed;
    if (step === "guide") return state.sections.storylines.confirmed;
    if (step === "export") return allConfirmed();
    return false;
  }

  function allConfirmed() {
    return Boolean(
      state.configConfirmed &&
      state.sections.worldview.confirmed &&
      state.sections.characters.confirmed &&
      state.sections.beatPlan.confirmed &&
      state.sections.storylines.confirmed &&
      state.sections.guide.confirmed
    );
  }

  function statusTag(section) {
    if (section === "basic") {
      return state.configConfirmed ? `<span class="fp-tag ok">已确认并锁定</span>` : `<span class="fp-tag blue">可编辑</span>`;
    }
    const s = state.sections[section];
    if (!s || s.status === "locked") return `<span class="fp-tag lock">待上游确认</span>`;
    if (s.confirmed) return `<span class="fp-tag ok">已确认并锁定</span>`;
    if (s.status === "generated") return `<span class="fp-tag blue">已生成，待确认</span>`;
    if (s.status === "edited") return `<span class="fp-tag warn">已更新，待确认</span>`;
    return `<span class="fp-tag">未生成</span>`;
  }

  function lockNote(sectionName) {
    return `<div class="fp-lock-note">该模块确认后会锁定，并解锁下游模块。进入下游后不允许继续修改上游，以避免后续策划内容和上游设定不一致。</div>`;
  }

  function render() {
    saveState();
    app.innerHTML = `
      <div class="fp-shell">
        ${renderSide()}
        <main class="fp-main">
          ${renderTop()}
          ${renderCurrentStep()}
        </main>
        ${renderFooter()}
        ${state.toast ? `<div class="fp-toast">${escapeHtml(state.toast)}</div>` : ""}
        ${state.modalLineId ? renderStorylineModal(state.modalLineId) : ""}
      </div>
    `;
  }

  function renderSide() {
    const nav = stepDefs.map(([id, label], index) => {
      const active = state.currentStep === id ? "active" : "";
      const done = isStepDone(id) ? "done" : "";
      const locked = !isUnlocked(id) ? "locked" : "";
      const clickable = isUnlocked(id) ? "can-click" : "";
      const mark = isStepDone(id) ? "✓" : String(index + 1);
      return `<div class="fp-nav-item ${active} ${done} ${locked} ${clickable}" data-step="${id}">
        <span>${index + 1}. ${escapeHtml(label)}</span><span class="fp-nav-pill">${mark}</span>
      </div>`;
    }).join("");

    return `
      <aside class="fp-side">
        <div class="fp-logo"><div class="fp-logo-mark">NS</div><div>NewStageMaker<small>框架策划工作台</small></div></div>
        <div class="fp-side-note">前端 Mock 版。当前页面只负责跑通结构、编辑、确认、锁定、JSON 输出。后端接入时替换 planningApi 即可。</div>
        <nav class="fp-nav">${nav}</nav>
      </aside>
    `;
  }

  function isStepDone(id) {
    if (id === "basic") return state.configConfirmed;
    if (id === "worldview") return state.sections.worldview.confirmed;
    if (id === "characters") return state.sections.characters.confirmed;
    if (id === "beatPlan") return state.sections.beatPlan.confirmed;
    if (id === "storylines") return state.sections.storylines.confirmed;
    if (id === "guide") return state.sections.guide.confirmed;
    if (id === "export") return allConfirmed();
    return false;
  }

  function renderTop() {
    return `
      <div class="fp-top">
        <div>
          <div class="fp-kicker">Framework Planning / 三幕十五节拍卡点规划</div>
          <h1 class="fp-title">${escapeHtml(state.config.projectTitle || "未命名框架策划")}</h1>
        </div>
        <div class="fp-top-actions">
          <button class="fp-btn small" data-action="copy-json">复制 JSON</button>
          <button class="fp-btn small danger" data-action="reset-demo">重置本地状态</button>
        </div>
      </div>
      <div class="fp-card fp-steps">${renderSteps()}</div>
    `;
  }

  function renderSteps() {
    return stepDefs.map(([id, label], index) => {
      const active = state.currentStep === id ? "active" : "";
      const done = isStepDone(id) ? "done" : "";
      const mark = isStepDone(id) ? "✓" : String(index + 1);
      const line = index < stepDefs.length - 1 ? `<span class="fp-step-line"></span>` : "";
      return `<div class="fp-step ${active} ${done}"><span class="fp-step-dot">${mark}</span><span>${escapeHtml(label)}</span></div>${line}`;
    }).join("");
  }

  function renderCurrentStep() {
    if (state.currentStep === "basic") return renderBasic();
    if (state.currentStep === "worldview") return renderTextSection("worldview", "世界观方案", "先确定故事的世界规则、冲突资源、势力结构、主矛盾和视觉气质。", "生成世界观方案");
    if (state.currentStep === "characters") return renderTextSection("characters", "人设方案", "基于已确认的世界观生成主角、反派、关键配角、人物目标、缺陷、关系和成长方向。", "生成人设方案");
    if (state.currentStep === "beatPlan") return renderBeatPlan();
    if (state.currentStep === "storylines") return renderStorylines();
    if (state.currentStep === "guide") return renderGuide();
    if (state.currentStep === "export") return renderExport();
    return renderBasic();
  }

  function renderBasic() {
    const c = state.config;
    const locked = state.configConfirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">基础配置</h2>
            <p class="fp-card-sub">上传材料和生成约束只作为前端状态保存。确认后基础配置锁定，才允许生成世界观方案。</p>
          </div>
          ${statusTag("basic")}
        </div>
        ${locked ? `<div class="fp-inline-warning">基础配置已确认并锁定。为了保证下游策划一致性，当前版本不允许回退修改。</div>` : ""}
        <div class="fp-grid two" style="margin-bottom:14px">
          <div class="fp-field">
            <label>项目标题</label>
            <input data-bind-config="projectTitle" value="${escapeHtml(c.projectTitle)}" ${locked ? "disabled" : ""} />
          </div>
          <div class="fp-field">
            <label>小说来源</label>
            <select data-bind-config="sourceType" ${locked ? "disabled" : ""}>
              <option value="upload" ${c.sourceType === "upload" ? "selected" : ""}>直接上传小说</option>
              <option value="library" ${c.sourceType === "library" ? "selected" : ""}>从已有小说选择</option>
            </select>
          </div>
        </div>
        <div class="fp-upload" style="margin-bottom:16px">
          <div>
            <strong>${c.fileName ? escapeHtml(c.fileName) : "尚未选择小说文件"}</strong>
            <p>当前 Mock 页不真实上传文件。可填写文件名模拟后续接入。</p>
            <div style="margin-top:10px; max-width:460px">
              <input data-bind-config="fileName" placeholder="例如：696_机甲纪元，拳爆天星.txt" value="${escapeHtml(c.fileName)}" ${locked ? "disabled" : ""} />
            </div>
          </div>
        </div>
        <div class="fp-grid">
          <div class="fp-field"><label>预计改编季数</label><input type="number" min="1" data-bind-config="seasonCount" value="${escapeHtml(c.seasonCount)}" ${locked ? "disabled" : ""} /></div>
          <div class="fp-field"><label>预计每季集数</label><input type="number" min="1" data-bind-config="episodesPerSeason" value="${escapeHtml(c.episodesPerSeason)}" ${locked ? "disabled" : ""} /></div>
          <div class="fp-field"><label>预计每集分钟数</label><input type="number" min="1" data-bind-config="minutesPerEpisode" value="${escapeHtml(c.minutesPerEpisode)}" ${locked ? "disabled" : ""} /></div>
        </div>
        <div class="fp-grid two" style="margin-top:14px">
          <div class="fp-field"><label>目标类型</label><input data-bind-config="targetGenre" value="${escapeHtml(c.targetGenre)}" ${locked ? "disabled" : ""} /></div>
          <div class="fp-field"><label>材料备注</label><input data-bind-config="materialNote" placeholder="可选：原作特点、禁改点、重点人物等" value="${escapeHtml(c.materialNote)}" ${locked ? "disabled" : ""} /></div>
        </div>
        <div class="fp-field" style="margin-top:14px">
          <label>改编思路</label>
          <textarea data-bind-config="adaptationDirection" ${locked ? "disabled" : ""}>${escapeHtml(c.adaptationDirection)}</textarea>
        </div>
        ${lockNote("基础配置")}
        <div class="fp-actions">
          <button class="fp-btn primary" data-action="confirm-basic" ${locked ? "disabled" : ""}>确认基础配置，进入世界观</button>
        </div>
      </section>
    `;
  }

  function renderTextSection(key, title, sub, generateLabel) {
    const s = state.sections[key];
    const locked = s.status === "locked";
    const confirmed = s.confirmed;
    const editing = s.editing;
    const body = locked
      ? `<div class="fp-empty">请先确认上游模块。</div>`
      : editing
        ? `<div class="fp-editor fp-field"><label>编辑${escapeHtml(title)}</label><textarea data-edit-buffer="${key}">${escapeHtml(editBuffers[key] ?? s.text)}</textarea></div>`
        : s.text
          ? `<div class="fp-text-block"><div class="fp-text">${formatText(s.text)}</div></div>`
          : `<div class="fp-empty">尚未生成。点击“${escapeHtml(generateLabel)}”后会出现 Mock 结果。</div>`;

    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">${escapeHtml(title)}</h2>
            <p class="fp-card-sub">${escapeHtml(sub)}</p>
          </div>
          ${statusTag(key)}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">${escapeHtml(title)}已确认并锁定。下游策划会基于该版本继续生成。</div>` : ""}
        ${body}
        ${lockNote(title)}
        <div class="fp-actions">
          ${editing ? `
            <button class="fp-btn" data-action="cancel-edit" data-section="${key}">取消</button>
            <button class="fp-btn primary" data-action="save-edit" data-section="${key}">更新${escapeHtml(title)}</button>
          ` : `
            <button class="fp-btn" data-action="generate-text" data-section="${key}" ${locked || confirmed ? "disabled" : ""}>${escapeHtml(generateLabel)}</button>
            <button class="fp-btn" data-action="edit-text" data-section="${key}" ${locked || confirmed || !s.text ? "disabled" : ""}>编辑</button>
            <button class="fp-btn primary" data-action="confirm-section" data-section="${key}" ${locked || confirmed || !s.text ? "disabled" : ""}>确认并进入下游</button>
          `}
        </div>
      </section>
    `;
  }

  function renderBeatPlan() {
    const s = state.sections.beatPlan;
    const locked = s.status === "locked";
    const confirmed = s.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">三幕十五节拍卡点规划时间轴</h2>
            <p class="fp-card-sub">这里把三幕十五节拍和卡点轴合并处理。每个节拍同时承担叙事功能、集数区间、阶段卡点和剧情推进说明。</p>
          </div>
          ${statusTag("beatPlan")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">三幕十五节拍卡点规划已确认并锁定。人物故事线会基于该时间轴拆分。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认人设方案。</div>` : s.items.length ? renderBeatTimeline(s.items) : `<div class="fp-empty">尚未生成三幕十五节拍卡点规划。</div>`}
        ${s.items.length ? renderBeatExplanation(s) : ""}
        ${lockNote("三幕十五节拍卡点规划")}
        <div class="fp-actions">
          <button class="fp-btn" data-action="generate-beat-plan" ${locked || confirmed ? "disabled" : ""}>生成十五节拍卡点规划</button>
          <button class="fp-btn" data-action="generate-beat-plan" data-regenerate="1" ${locked || confirmed || !s.items.length ? "disabled" : ""}>重新生成</button>
          <button class="fp-btn primary" data-action="confirm-section" data-section="beatPlan" ${locked || confirmed || !s.items.length ? "disabled" : ""}>确认并进入人物故事线</button>
        </div>
      </section>
    `;
  }

  function renderBeatTimeline(items) {
    const nodes = items.map((item) => `
      <div class="fp-beat-node">
        <div class="fp-beat-act">${escapeHtml(item.act)}</div>
        <div class="fp-beat-title">${item.index}. ${escapeHtml(item.title)}</div>
        <div class="fp-beat-dot"></div>
        <div class="fp-beat-range">${escapeHtml(item.episodeRange)}</div>
      </div>
    `).join("");
    return `<div class="fp-timeline-wrap"><div class="fp-timeline">${nodes}</div></div>`;
  }

  function renderBeatExplanation(s) {
    const cards = s.items.map((item) => `
      <article class="fp-beat-card">
        <h3>${item.index}. ${escapeHtml(item.title)}</h3>
        <div class="fp-beat-meta">${escapeHtml(item.act)} · ${escapeHtml(item.episodeRange)} · ${escapeHtml(item.cardName)}</div>
        <p><strong>叙事功能：</strong>${escapeHtml(item.function)}</p>
        <p><strong>剧情内容：</strong>${escapeHtml(item.content)}</p>
        <p><strong>结尾钩子：</strong>${escapeHtml(item.hook)}</p>
      </article>
    `).join("");
    return `
      <div style="margin-top:16px">
        <div class="fp-card-title-row" style="margin-bottom:10px">
          <div><h2 class="fp-card-title">三幕十五节拍卡点说明</h2><p class="fp-card-sub">卡点说明不是额外结构，而是对同一条十五节拍时间轴的详细解释。</p></div>
        </div>
        <div class="fp-text-block" style="margin-bottom:14px"><div class="fp-text">${formatText(s.explanation)}</div></div>
        <div class="fp-beat-card-grid">${cards}</div>
      </div>
    `;
  }

  function renderStorylines() {
    const s = state.sections.storylines;
    const locked = s.status === "locked";
    const confirmed = s.confirmed;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">不同人物故事线</h2>
            <p class="fp-card-sub">基于已确认的十五节拍卡点，拆分不同人物或关系线索。用户可以查看详细分布，并选择保留、精简或删除。</p>
          </div>
          ${statusTag("storylines")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">人物故事线已确认并锁定。整体改编指引会基于这些取舍继续生成。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认三幕十五节拍卡点规划。</div>` : s.items.length ? renderStorylineGrid(s.items, confirmed) : `<div class="fp-empty">尚未生成不同人物故事线。</div>`}
        ${lockNote("不同人物故事线")}
        <div class="fp-actions">
          <button class="fp-btn" data-action="generate-storylines" ${locked || confirmed ? "disabled" : ""}>生成人物故事线</button>
          <button class="fp-btn" data-action="generate-storylines" data-regenerate="1" ${locked || confirmed || !s.items.length ? "disabled" : ""}>重新生成</button>
          <button class="fp-btn primary" data-action="confirm-section" data-section="storylines" ${locked || confirmed || !s.items.length ? "disabled" : ""}>确认并进入改编指引</button>
        </div>
      </section>
    `;
  }

  function decisionLabel(value) {
    return { keep: "保留", simplify: "精简", delete: "删除" }[value] || value;
  }

  function decisionTag(value) {
    const cls = value === "keep" ? "blue" : value === "simplify" ? "warn" : "red";
    return `<span class="fp-tag ${cls}">${decisionLabel(value)}</span>`;
  }

  function renderStorylineGrid(items, confirmed) {
    return `<div class="fp-story-grid">${items.map((line) => `
      <article class="fp-story-card">
        <div class="fp-story-head">
          <h3>${escapeHtml(line.title)}</h3>
          ${decisionTag(line.decision)}
        </div>
        <p>${escapeHtml(line.summary)}</p>
        <div class="fp-radio-row">
          ${["keep", "simplify", "delete"].map((v) => `<label><input type="radio" name="decision-${line.id}" data-action="change-storyline-decision" data-id="${line.id}" value="${v}" ${line.decision === v ? "checked" : ""} ${confirmed ? "disabled" : ""} /> ${decisionLabel(v)}</label>`).join("")}
        </div>
        <div class="fp-actions" style="margin-top:0">
          <button class="fp-btn small" data-action="open-storyline" data-id="${line.id}">查看详细故事线</button>
          <button class="fp-btn small" data-action="open-storyline" data-id="${line.id}" ${confirmed ? "disabled" : ""}>编辑</button>
        </div>
      </article>
    `).join("")}</div>`;
  }

  function renderStorylineModal(id) {
    const line = state.sections.storylines.items.find((item) => item.id === id);
    if (!line) return "";
    const confirmed = state.sections.storylines.confirmed;
    const detailItems = (line.distribution || []).map((part, index) => `
      <div class="fp-detail-item">
        <strong>${escapeHtml(part.range)}：${escapeHtml(part.title)}</strong>
        ${escapeHtml(part.content)}
      </div>
    `).join("");
    return `
      <div class="fp-modal-mask" data-action="close-modal">
        <div class="fp-modal" data-modal-content="1">
          <div class="fp-modal-head">
            <div>
              <h2>${escapeHtml(line.title)}</h2>
              <p class="fp-modal-sub">查看这条人物故事线在十五节拍卡点中的集数分布。未确认前可以编辑摘要、处理方式和分布说明。</p>
            </div>
            <button class="fp-btn small" data-action="close-modal">关闭</button>
          </div>
          <div class="fp-field" style="margin-bottom:12px">
            <label>故事线摘要</label>
            <textarea data-modal-field="summary" ${confirmed ? "disabled" : ""}>${escapeHtml(line.summary)}</textarea>
          </div>
          <div class="fp-field" style="margin-bottom:12px">
            <label>处理方式</label>
            <select data-modal-field="decision" ${confirmed ? "disabled" : ""}>
              <option value="keep" ${line.decision === "keep" ? "selected" : ""}>保留</option>
              <option value="simplify" ${line.decision === "simplify" ? "selected" : ""}>精简</option>
              <option value="delete" ${line.decision === "delete" ? "selected" : ""}>删除</option>
            </select>
          </div>
          <div class="fp-field">
            <label>详细分布补充</label>
            <textarea data-modal-field="detailNote" ${confirmed ? "disabled" : ""}>${escapeHtml(line.detailNote || "")}</textarea>
          </div>
          <div class="fp-detail-list">${detailItems}</div>
          <div class="fp-actions">
            <button class="fp-btn" data-action="close-modal">关闭</button>
            <button class="fp-btn primary" data-action="save-storyline-modal" data-id="${line.id}" ${confirmed ? "disabled" : ""}>更新故事线</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderGuide() {
    const s = state.sections.guide;
    const locked = s.status === "locked";
    const confirmed = s.confirmed;
    const editing = s.editing;
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">整体改编指引四项</h2>
            <p class="fp-card-sub">该模块用于把前面的设定、卡点和故事线取舍转成后续剧本工作流的约束。</p>
          </div>
          ${statusTag("guide")}
        </div>
        ${confirmed ? `<div class="fp-inline-warning">整体改编指引已确认并锁定。现在可以输出最终 JSON 策划包。</div>` : ""}
        ${locked ? `<div class="fp-empty">请先确认不同人物故事线。</div>` : editing ? renderGuideEditor(s.items) : s.items.length ? renderGuideCards(s.items) : `<div class="fp-empty">尚未生成整体改编指引。</div>`}
        ${lockNote("整体改编指引")}
        <div class="fp-actions">
          ${editing ? `
            <button class="fp-btn" data-action="cancel-guide-edit">取消</button>
            <button class="fp-btn primary" data-action="save-guide-edit">更新改编指引</button>
          ` : `
            <button class="fp-btn" data-action="generate-guide" ${locked || confirmed ? "disabled" : ""}>生成改编指引</button>
            <button class="fp-btn" data-action="edit-guide" ${locked || confirmed || !s.items.length ? "disabled" : ""}>编辑</button>
            <button class="fp-btn primary" data-action="confirm-section" data-section="guide" ${locked || confirmed || !s.items.length ? "disabled" : ""}>确认并输出 JSON</button>
          `}
        </div>
      </section>
    `;
  }

  function renderGuideCards(items) {
    return `<div class="fp-guide-grid">${items.map((item) => `
      <article class="fp-guide-card">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.content)}</p>
      </article>
    `).join("")}</div>`;
  }

  function renderGuideEditor(items) {
    return `<div class="fp-guide-grid">${items.map((item, index) => `
      <div class="fp-field">
        <label>${escapeHtml(item.title)}</label>
        <textarea data-guide-index="${index}">${escapeHtml(item.content)}</textarea>
      </div>
    `).join("")}</div>`;
  }

  function renderExport() {
    const payload = buildPayload();
    return `
      <section class="fp-card fp-section">
        <div class="fp-card-title-row">
          <div>
            <h2 class="fp-card-title">最终 JSON 策划包输出</h2>
            <p class="fp-card-sub">后续接入剧本工作流时，建议把这个 JSON 作为框架生成结果传入，而不是只传一段自然语言。</p>
          </div>
          ${allConfirmed() ? `<span class="fp-tag ok">可提交</span>` : `<span class="fp-tag warn">仍有模块未确认</span>`}
        </div>
        ${allConfirmed() ? "" : `<div class="fp-empty">请先完成全部上游确认。</div>`}
        <pre class="fp-json">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
        <div class="fp-actions">
          <button class="fp-btn" data-action="copy-json">复制 JSON</button>
          <button class="fp-btn primary" data-action="submit-mock" ${allConfirmed() ? "" : "disabled"}>Mock 提交到后续剧本工作流</button>
        </div>
      </section>
    `;
  }

  function renderFooter() {
    const idx = stepIndex(state.currentStep);
    const prev = stepDefs[idx - 1] && stepDefs[idx - 1][0];
    const next = stepDefs[idx + 1] && stepDefs[idx + 1][0];
    return `
      <div class="fp-footer">
        <div class="fp-footer-note">本地状态自动保存。上游确认后锁定；下游只能基于已确认版本继续。</div>
        <div class="fp-top-actions">
          <button class="fp-btn" data-action="go-step" data-step="${prev || ""}" ${!prev ? "disabled" : ""}>上一步</button>
          <button class="fp-btn primary" data-action="go-step" data-step="${next || ""}" ${!next || !isUnlocked(next) ? "disabled" : ""}>下一步</button>
        </div>
      </div>
    `;
  }

  const planningApi = {
    generateWorldview: async () => {
      const title = state.config.projectTitle || "项目";
      return `世界观方案：${title}\n\n1. 世界类型：近未来都市与高压竞技体系结合的短剧世界。社会资源被少数强势组织、资本平台或隐秘规则掌控，普通人必须通过某种竞赛、考核、交易或权力系统争取上升机会。\n\n2. 核心规则：主角进入的世界不是自由竞争，而是被规则、排名、身份和资源准入限制的封闭场域。每一次胜利都会打开更高层级，同时暴露更大的代价。\n\n3. 核心资源：资源可以是名额、系统权限、证据、机缘、家族继承权、关键技术或情感信任。它必须能直接推动剧情升级，而不是只做背景装饰。\n\n4. 主矛盾：底层主角被压迫或被误判，通过持续破局挑战既有秩序。反派代表既得利益、伪规则或隐秘操盘者。\n\n5. 视觉气质：场景要有强识别度，避免纯口述信息。关键冲突尽量外化为竞赛、对峙、公开羞辱、限时任务、身份揭露或资源争夺。`;
    },
    generateCharacters: async () => `人设方案\n\n1. 主角：底层出身或被排挤的年轻人，表面弱势，内在有强烈不服输意志。核心缺陷是过度逞强或不信任他人，成长方向是从单点反击走向主动承担。\n\n2. 反派：既得利益集团中的直接压迫者，擅长利用规则制造不公平。其压迫方式不能只靠坏，而要靠身份、资源和信息差。\n\n3. B故事人物：可以是同伴、师徒、亲密关系或对照角色。作用是让主角不只是升级打脸，也能在情感和价值观上完成变化。\n\n4. 关键配角：负责提供信息、制造误会、推动任务、制造阶段性阻碍。每个配角都应绑定一条明确功能，避免只做装饰性人物。\n\n5. 人物关系：主角与反派形成正面对抗；主角与B故事人物形成信任修复；主角与配角形成阶段性联盟或背叛。`,
    generateBeatPlan: async () => {
      const total = Math.max(15, Number(state.config.episodesPerSeason) || 50);
      const ranges = splitEpisodeRanges(total);
      const defs = [
        [1, "开场", "第一幕", "开局卡", "用强处境和强画面立住主角困境。", "主角在公开场合被羞辱或遭遇重大损失，但他没有彻底屈服。", "结尾抛出主角即将触碰新规则的机会。"],
        [2, "主体呈现", "第一幕", "人设卡", "展示主角日常、缺陷、欲望和外部压力。", "让观众知道主角为什么必须改变，也知道他现在为什么改变不了。", "主角的旧生活被进一步压缩。"],
        [3, "铺垫", "第一幕", "伏笔卡", "埋下规则、人物关系、关键资源和后续反转。", "关键道具、身份误会、反派压迫和B故事人物第一次进入叙事。", "伏笔和危机同时出现。"],
        [4, "推动催化剂", "第一幕", "引爆卡", "打破平衡，让主角无法回到原状态。", "主角被迫参加挑战、接受任务、卷入阴谋或获得系统入口。", "主角必须在短时间内做选择。"],
        [5, "争执", "第一幕", "抗拒卡", "展示主角犹豫、误判、抗拒或关系冲突。", "主角与同伴、家人、旧秩序或自己发生冲突，明确进入主线的代价。", "旧选择已经不再可行。"],
        [6, "第二幕衔接点", "第一幕", "入局卡", "主角正式跨入第二幕的新行动场。", "主角接受挑战，第一次主动进入规则内部，故事从被动受压转为主动破局。", "更大的对手注意到主角。"],
        [7, "B故事线", "第二幕", "情感卡", "建立情感线、伙伴线、师徒线或价值观线。", "B故事人物与主角形成合作、冲突或互相利用，为后续主题变化埋点。", "关系中出现未解决的信任问题。"],
        [8, "游戏及斗争", "第二幕", "爽点卡", "兑现类型承诺和高频戏剧冲突。", "主角不断破解小关卡，完成打脸、逆袭、斗争、解谜或升级。", "阶段胜利背后埋下更危险的反噬。"],
        [9, "中点", "第二幕", "反转卡", "第二幕高潮，阶段性胜利或重大反转。", "主角获得一次看似决定性的胜利，或者发现真正敌人和真正规则。", "局势从局部斗争升级为全面对抗。"],
        [10, "危险逼近", "第二幕", "围剿卡", "反派、环境和关系压力开始合围。", "主角此前有效的办法失效，隐藏代价显现，盟友开始动摇。", "主角失去一个关键支点。"],
        [11, "一败涂地", "第二幕", "崩盘卡", "让主角遭遇重大失败。", "主角计划被识破、资源被夺、关系破裂或身份暴露，进入全剧最低行动点。", "表面上主角已经没有胜算。"],
        [12, "灵魂黑夜", "第二幕", "低谷卡", "主角完成内在转向。", "主角意识到真正问题不是单次胜负，而是自己过去的缺陷、恐惧或错误目标。", "B故事线给出新的理解或关键支持。"],
        [13, "第三幕衔接点", "第三幕", "反攻卡", "主角找到新解法，进入第三幕。", "主角把主线行动和B故事的情感/主题领悟合并，形成新的反击策略。", "反派以为主角仍按旧方式行动。"],
        [14, "结局", "第三幕", "决战卡", "最终对抗和核心矛盾解决。", "主角在公开或高压场景中完成最终破局，反派规则被击穿，主要人物关系完成归位。", "胜利带来新的世界状态。"],
        [15, "终场画面", "第三幕", "闭环卡", "展示变化后的主角和世界。", "用与开场形成对照的画面呈现主角成长、关系修复和世界秩序变化。", "为后续季或后续剧本留下可控余味。"]
      ];
      const items = defs.map((d, i) => ({
        index: d[0], title: d[1], act: d[2], cardName: d[3], function: d[4], content: d[5], hook: d[6], episodeRange: ranges[i]
      }));
      const explanation = `整体卡点策略：该时间轴把三幕十五节拍直接落到集数。第一幕负责强开局、立人物、给出催化事件并让主角入局；第二幕负责类型爽点、B故事、阶段反转、危机围剿和最低谷；第三幕负责反攻、决战和终场闭环。\n\n节奏要求：前3个节拍必须尽快完成主角处境、核心冲突和观众钩子；第6节拍必须让主角正式进入主线；第9节拍是全季中段反转；第11至12节拍是最低谷与内在转向；第14至15节拍完成主矛盾解决和视觉闭环。`;
      return { items, explanation };
    },
    generateStorylines: async () => [
      {
        id: "protagonist_growth",
        title: "主角成长线",
        decision: "keep",
        summary: "主角从被压迫、被误判、被规则限制，逐步成长为主动破局并承担代价的人。",
        detailNote: "重点保留，后续剧本需要持续体现主角从被动到主动的变化。",
        distribution: [
          { range: "1-3节拍", title: "困境建立", content: "主角处于低位，缺陷和欲望被清楚展示。" },
          { range: "4-6节拍", title: "被迫入局", content: "催化事件打破原状，主角进入新规则。" },
          { range: "8-9节拍", title: "阶段成长", content: "主角通过斗争获得胜利，但也暴露更大的盲点。" },
          { range: "11-13节拍", title: "崩盘与重建", content: "失败后完成内在转向，找到新的反击方式。" },
          { range: "14-15节拍", title: "完成闭环", content: "最终行动证明主角已经不再是开场时的自己。" }
        ]
      },
      {
        id: "antagonist_pressure",
        title: "反派压迫线",
        decision: "keep",
        summary: "反派通过规则、资源、身份和信息差不断压迫主角，推动冲突升级。",
        detailNote: "反派不能只做坏人，应承担制度压力和阶段危机的制造功能。",
        distribution: [
          { range: "1-5节拍", title: "压迫显形", content: "反派或其代理人制造主角最初困境。" },
          { range: "6-9节拍", title: "规则对抗", content: "主角入局后不断挑战反派设置的规则。" },
          { range: "10-12节拍", title: "全面围剿", content: "反派集中资源让主角一败涂地。" },
          { range: "13-14节拍", title: "最终反制", content: "主角利用新认知击穿反派规则。" }
        ]
      },
      {
        id: "b_story_relationship",
        title: "B故事情感线",
        decision: "simplify",
        summary: "B故事人物帮助主角完成情感和价值观转向，但不应压过主线节奏。",
        detailNote: "建议精简为关键节点出现，承担主题支撑而不是展开独立支线。",
        distribution: [
          { range: "3-7节拍", title: "关系建立", content: "B故事人物出现，与主角形成误解、合作或互相试探。" },
          { range: "8-10节拍", title: "关系推进", content: "关系帮助主角看到自己旧方法的局限。" },
          { range: "12-13节拍", title: "主题回流", content: "B故事线促成主角在最低谷后的新选择。" },
          { range: "15节拍", title: "情感闭环", content: "在终场画面中完成关系状态的变化。" }
        ]
      },
      {
        id: "secret_reveal",
        title: "秘密揭露线",
        decision: "keep",
        summary: "围绕身份、规则真相或核心资源来源持续埋伏笔，并在中点和第三幕前回收。",
        detailNote: "该线负责悬念和反转，建议保留。",
        distribution: [
          { range: "2-3节拍", title: "埋下异常", content: "早期出现看似不起眼的异常信息。" },
          { range: "8-9节拍", title: "中点揭露", content: "揭露一层真相，让故事升级。" },
          { range: "11-12节拍", title: "真相代价", content: "秘密带来主角失败或关系崩塌。" },
          { range: "13-14节拍", title: "最终回收", content: "主角用真相完成反击。" }
        ]
      }
    ],
    generateGuide: async () => [
      { title: "1. 核心设定调整", content: "保留核心规则、核心资源和主角低位逆袭的基本结构。可以改动具体场景和任务形式，但不能削弱主角与规则体系之间的矛盾。" },
      { title: "2. 叙事节奏与结构", content: "采用强开局、高频小高潮和中段反转结构。前3节拍必须快速抓人；第8至9节拍集中兑现类型爽点；第11至12节拍制造全季最低谷。" },
      { title: "3. 视觉化呈现", content: "尽量把心理活动转成可拍摄动作、公开对峙、限时任务、排名变化、证据展示、空间压迫和视觉化道具。避免长段解释。" },
      { title: "4. 角色与情绪塑造", content: "主角情绪从屈辱、不甘、逞强，转向清醒、承担和反攻。反派压迫要持续升级；B故事线负责补足信任、代价和主题回流。" }
    ]
  };

  function splitEpisodeRanges(total) {
    const weights = [3, 4, 4, 4, 4, 5, 5, 7, 5, 5, 4, 4, 3, 2, 1];
    const sum = weights.reduce((a, b) => a + b, 0);
    let start = 1;
    return weights.map((w, idx) => {
      const remaining = 15 - idx;
      let len = idx === weights.length - 1 ? total - start + 1 : Math.max(1, Math.round(total * w / sum));
      if (start + len + remaining - 2 > total) len = Math.max(1, total - start - remaining + 2);
      const end = Math.min(total, start + len - 1);
      const range = start === end ? `第${start}集` : `第${start}-${end}集`;
      start = end + 1;
      return range;
    });
  }

  function buildPayload() {
    return {
      schemaVersion: "framework-planner-v2",
      status: allConfirmed() ? "confirmed" : "draft",
      basicConfig: clone(state.config),
      confirmed: {
        basic: state.configConfirmed,
        worldview: state.sections.worldview.confirmed,
        characters: state.sections.characters.confirmed,
        beatPlan: state.sections.beatPlan.confirmed,
        storylines: state.sections.storylines.confirmed,
        guide: state.sections.guide.confirmed
      },
      frameworkPlan: {
        worldviewPlan: state.sections.worldview.text,
        characterPlan: state.sections.characters.text,
        threeActFifteenBeatCheckpointTimeline: state.sections.beatPlan.items,
        threeActFifteenBeatCheckpointExplanation: state.sections.beatPlan.explanation,
        characterStorylines: state.sections.storylines.items,
        adaptationGuide: state.sections.guide.items
      },
      userDecisions: {
        storylineActions: state.sections.storylines.items.map((line) => ({ id: line.id, title: line.title, decision: line.decision }))
      }
    };
  }

  function unlockSection(key) {
    const section = state.sections[key];
    if (section && section.status === "locked") section.status = "empty";
  }

  function goStep(id) {
    if (!id) return;
    if (!isUnlocked(id)) {
      showToast("请先确认上游模块");
      return;
    }
    state.currentStep = id;
    render();
  }

  function readGuideEditor() {
    const next = clone(state.sections.guide.items);
    document.querySelectorAll("[data-guide-index]").forEach((el) => {
      const idx = Number(el.dataset.guideIndex);
      if (next[idx]) next[idx].content = el.value;
    });
    return next;
  }

  app.addEventListener("input", (event) => {
    const el = event.target;
    if (el.matches("[data-bind-config]")) {
      const key = el.dataset.bindConfig;
      const value = el.type === "number" ? Number(el.value) : el.value;
      state.config[key] = value;
      if (key === "projectTitle") state.config.projectTitle = value;
      saveState();
    }
    if (el.matches("[data-edit-buffer]")) {
      editBuffers[el.dataset.editBuffer] = el.value;
    }
  });

  app.addEventListener("click", async (event) => {
    const modalContent = event.target.closest("[data-modal-content]");
    const actionEl = event.target.closest("[data-action]");
    const sideStep = event.target.closest("[data-step]");

    if (sideStep && sideStep.classList.contains("can-click") && !actionEl) {
      goStep(sideStep.dataset.step);
      return;
    }

    if (!actionEl) return;
    const action = actionEl.dataset.action;

    if (action === "close-modal" && modalContent) return;
    if (action === "close-modal") {
      state.modalLineId = null;
      render();
      return;
    }

    if (action === "go-step") {
      goStep(actionEl.dataset.step);
      return;
    }

    if (action === "reset-demo") {
      if (confirm("确认重置本地框架策划状态？")) {
        localStorage.removeItem(STORAGE_KEY);
        state = clone(initialState);
        editBuffers = {};
        render();
      }
      return;
    }

    if (action === "copy-json") {
      await navigator.clipboard.writeText(JSON.stringify(buildPayload(), null, 2));
      showToast("已复制 JSON");
      return;
    }

    if (action === "submit-mock") {
      showToast("Mock 提交成功。后续可替换成真实剧本工作流接口。");
      return;
    }

    if (action === "confirm-basic") {
      if (!state.config.projectTitle || !state.config.adaptationDirection) {
        showToast("请至少填写项目标题和改编思路");
        return;
      }
      state.configConfirmed = true;
      unlockSection("worldview");
      state.currentStep = "worldview";
      showToast("基础配置已确认并锁定");
      render();
      return;
    }

    if (action === "generate-text") {
      const section = actionEl.dataset.section;
      if (section === "worldview") state.sections.worldview.text = await planningApi.generateWorldview();
      if (section === "characters") state.sections.characters.text = await planningApi.generateCharacters();
      state.sections[section].status = "generated";
      state.sections[section].confirmed = false;
      showToast(`${section === "worldview" ? "世界观" : "人设"}已生成`);
      render();
      return;
    }

    if (action === "edit-text") {
      const section = actionEl.dataset.section;
      state.sections[section].editing = true;
      editBuffers[section] = state.sections[section].text;
      render();
      return;
    }

    if (action === "cancel-edit") {
      const section = actionEl.dataset.section;
      state.sections[section].editing = false;
      delete editBuffers[section];
      render();
      return;
    }

    if (action === "save-edit") {
      const section = actionEl.dataset.section;
      state.sections[section].text = editBuffers[section] ?? state.sections[section].text;
      state.sections[section].editing = false;
      state.sections[section].status = "edited";
      state.sections[section].confirmed = false;
      delete editBuffers[section];
      showToast("已更新，仍需确认后才能进入下游");
      render();
      return;
    }

    if (action === "generate-beat-plan") {
      const result = await planningApi.generateBeatPlan();
      state.sections.beatPlan.items = result.items;
      state.sections.beatPlan.explanation = result.explanation;
      state.sections.beatPlan.status = "generated";
      state.sections.beatPlan.confirmed = false;
      showToast("十五节拍卡点规划已生成");
      render();
      return;
    }

    if (action === "generate-storylines") {
      state.sections.storylines.items = await planningApi.generateStorylines();
      state.sections.storylines.status = "generated";
      state.sections.storylines.confirmed = false;
      showToast("人物故事线已生成");
      render();
      return;
    }

    if (action === "change-storyline-decision") {
      const line = state.sections.storylines.items.find((item) => item.id === actionEl.dataset.id);
      if (line && !state.sections.storylines.confirmed) {
        line.decision = actionEl.value;
        state.sections.storylines.status = "edited";
        state.sections.storylines.confirmed = false;
        saveState();
      }
      return;
    }

    if (action === "open-storyline") {
      state.modalLineId = actionEl.dataset.id;
      render();
      return;
    }

    if (action === "save-storyline-modal") {
      const line = state.sections.storylines.items.find((item) => item.id === actionEl.dataset.id);
      if (line && !state.sections.storylines.confirmed) {
        const summary = document.querySelector('[data-modal-field="summary"]');
        const decision = document.querySelector('[data-modal-field="decision"]');
        const detailNote = document.querySelector('[data-modal-field="detailNote"]');
        line.summary = summary ? summary.value : line.summary;
        line.decision = decision ? decision.value : line.decision;
        line.detailNote = detailNote ? detailNote.value : line.detailNote;
        state.sections.storylines.status = "edited";
        state.sections.storylines.confirmed = false;
        state.modalLineId = null;
        showToast("故事线已更新，仍需确认");
        render();
      }
      return;
    }

    if (action === "generate-guide") {
      state.sections.guide.items = await planningApi.generateGuide();
      state.sections.guide.status = "generated";
      state.sections.guide.confirmed = false;
      showToast("改编指引已生成");
      render();
      return;
    }

    if (action === "edit-guide") {
      state.sections.guide.editing = true;
      render();
      return;
    }

    if (action === "cancel-guide-edit") {
      state.sections.guide.editing = false;
      render();
      return;
    }

    if (action === "save-guide-edit") {
      state.sections.guide.items = readGuideEditor();
      state.sections.guide.editing = false;
      state.sections.guide.status = "edited";
      state.sections.guide.confirmed = false;
      showToast("改编指引已更新，仍需确认");
      render();
      return;
    }

    if (action === "confirm-section") {
      const section = actionEl.dataset.section;
      state.sections[section].confirmed = true;
      state.sections[section].editing = false;
      if (section === "worldview") {
        unlockSection("characters");
        state.currentStep = "characters";
      } else if (section === "characters") {
        unlockSection("beatPlan");
        state.currentStep = "beatPlan";
      } else if (section === "beatPlan") {
        unlockSection("storylines");
        state.currentStep = "storylines";
      } else if (section === "storylines") {
        unlockSection("guide");
        state.currentStep = "guide";
      } else if (section === "guide") {
        state.currentStep = "export";
      }
      showToast("已确认并锁定，已进入下游");
      render();
      return;
    }
  });

  render();
})();
