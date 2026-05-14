import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { URL, fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const appJsPath = path.join(__dirname, "..", "app", "web", "static", "app.js");
const source = fs.readFileSync(appJsPath, "utf8");

function extractBetween(startToken, endToken) {
  const start = source.indexOf(startToken);
  assert.notEqual(start, -1, `missing token: ${startToken}`);
  let end = source.indexOf(endToken, start);
  if (end === -1) {
    end = source.indexOf(endToken.trimStart(), start);
  }
  assert.notEqual(end, -1, `missing token: ${endToken}`);
  return source.slice(start, end).trim();
}

const bootstrap = [
  'const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);',
  "const MAX_EXPECTATION_LINES = 5;",
  "const state = { expandedUserPrompts: {} };",
  extractBetween("function normalizeNumber(value) {", "\n\n  function currentUrl() {"),
  extractBetween("function currentUrl() {", "\n\n  function updateUrlParams(mutator) {"),
  extractBetween("function buildWorkspaceUrl({ projectId = null, fresh = false, scriptFormatMode = \"\" } = {}) {", "\n\n  function switchToFreshWorkspace() {"),
  extractBetween("function promptToggleKey(snapshot) {", "\n\n  function inputLineCount(text) {"),
  extractBetween("function inputLineCount(text) {", "\n\n  function syncExpectationInputHeight() {"),
  extractBetween("function normalizeScriptFormatMode(value) {", "\n\n  function selectedScriptFormatMode() {"),
  extractBetween("function scriptFormatModeLabel(value) {", "\n\n  function syncScriptFormatModeUi(snapshot = null) {"),
  extractBetween("function normalizeStageKey(stageKey) {", "\n\n  function formatDisplayValue(value) {"),
  extractBetween("function formatDisplayValue(value) {", "\n\n  // 把框架阶段的多个正式产物拼成一个完整回复，方便在聊天流里整体展示。"),
  extractBetween("function compactMessageText(value) {", "\n\n  async function copyTextToClipboard(text) {"),
  extractBetween("function runtimeLoadingSuffix(snapshot, nowMs = Date.now()) {", "\n\n  function defaultRuntimeMessage(snapshot) {"),
  extractBetween("function defaultRuntimeMessage(snapshot) {", "\n\n  // 当前状态下只保留必要提示，避免和“当前阶段”重复。"),
  extractBetween("function statusNoteFrom(snapshot, nowMs = Date.now()) {", "\n\n  function creationStatusLabel(snapshot) {"),
  extractBetween("function creationStatusLabel(snapshot) {", "\n\n  // 把后端阶段名统一折叠成前端可识别的正式阶段键。"),
  extractBetween("function frameworkStageOutput(snapshot) {", "\n\n  function worldviewStageOutput(snapshot) {"),
  extractBetween("function worldviewStageOutput(snapshot) {", "\n\n  // 只把平台真正对外公开的正式阶段产物整理成聊天消息。"),
  extractBetween("function visibleStageMessages(snapshot) {", "\n\n  // 内部阶段统一折叠成“思考分析”，避免把中间工作流细节直接暴露给用户。"),
  extractBetween("function thinkingStateFrom(snapshot) {", "\n\n  function userPromptSummary(snapshot) {"),
  extractBetween("function userPromptSummary(snapshot) {", "\n\n  function userPromptCopyText(snapshot) {"),
  extractBetween("function thinkingMessageCopyText(snapshot) {", "\n\n  function renderCopyButton(kind, key) {"),
  extractBetween("function escapeHtml(text) {", "\n\n  // 优先使用后端返回的辅助工具定义，拿不到时退回本地默认配置，保证主页面不会被工具区拖垮。"),
  extractBetween("function renderCopyButton(kind, key) {", "\n\n  function renderUserPromptBubble(snapshot) {"),
  extractBetween("function renderUserPromptBubble(snapshot) {", "\n\n  function renderAssistantStageBubble(message) {"),
  extractBetween("function renderAssistantStageBubble(message) {", "\n\n  function renderThinkingBubble(thinkingState) {"),
  extractBetween("function renderThinkingBubble(thinkingState) {", "\n\n  function transcriptSignature(snapshot) {"),
  extractBetween("function flashCopyButton(button, label) {", "\n\n  function projectTooltip(item) {"),
  "module.exports = { buildWorkspaceUrl, normalizeScriptFormatMode, scriptFormatModeLabel, formatDisplayValue, normalizeStageKey, compactMessageText, partialScriptOutput, statusNoteFrom, frameworkStageOutput, worldviewStageOutput, visibleStageMessages, thinkingStateFrom, thinkingMessageCopyText, renderCopyButton, renderUserPromptBubble, renderAssistantStageBubble, renderThinkingBubble, renderTextWithLineBreaks, flashCopyButton };",
].join("\n\n");

const context = {
  module: { exports: {} },
  exports: {},
  JSON,
  String,
  Array,
  Boolean,
  Number,
  Set,
  URL,
  window: {
    location: {
      href: "https://example.test/workspace?auth_token=token123",
    },
    scriptMakerConfig: {
      workspaceUrl: "/workspace",
    },
    setTimeout: (fn) => fn(),
  },
};
vm.runInNewContext(bootstrap, context, { filename: appJsPath });

const {
  statusNoteFrom,
  partialScriptOutput,
  formatDisplayValue,
  frameworkStageOutput,
  worldviewStageOutput,
  visibleStageMessages,
  thinkingStateFrom,
  thinkingMessageCopyText,
  renderCopyButton,
  renderUserPromptBubble,
  renderAssistantStageBubble,
  renderThinkingBubble,
  renderTextWithLineBreaks,
  flashCopyButton,
  buildWorkspaceUrl,
  normalizeScriptFormatMode,
  scriptFormatModeLabel,
} = context.module.exports;

test("build workspace url keeps waibao script format mode for fresh workspace", () => {
  const url = buildWorkspaceUrl({ fresh: true, scriptFormatMode: "waibao" });

  assert.match(url, /mode=new/);
  assert.match(url, /script_format_mode=waibao/);
});

test("script format mode label distinguishes waibao from default", () => {
  assert.equal(normalizeScriptFormatMode("waibao"), "waibao");
  assert.equal(scriptFormatModeLabel("waibao"), "外包专属格式");
  assert.equal(scriptFormatModeLabel(""), "标准格式");
});

test("framework natural language is preferred over structured raw artifacts", () => {
  const output = frameworkStageOutput({
    artifacts: {
      framework_natural_language: "框架自然语言版",
      story_outline: { opening: "故事开场" },
      character_bios: [{ name: "林夏" }],
      core_scene_input: { scene: "深夜会议室" },
      episode_plan: { episodes: [{ episode: 1, title: "危机来临" }] },
    },
  });

  assert.equal(output, "框架自然语言版");
  assert.equal(output.includes("[object Object]"), false);
});

test("worldview natural language is preferred over raw worldview json", () => {
  const output = worldviewStageOutput({
    artifacts: {
      worldview_natural_language: "世界观自然语言版",
      worldview: { worldview_summary: "资源紧张的近未来都市。" },
    },
  });

  assert.equal(output, "世界观自然语言版");
  assert.equal(output.includes("worldview_summary"), false);
});

test("framework and worldview do not pre-render placeholder outputs before natural language is ready", () => {
  const frameworkOutput = frameworkStageOutput({
    artifacts: {
      script_title_content: "测试项目",
      story_outline: { opening: "故事开场", theme: "身份与选择" },
      character_bios: [{ name: "林夏", goal: "保住工作" }],
      core_scene_input: { core_scene: "深夜会议室对峙" },
      episode_plan_display: { episodes: [{ episode: 1, title: "危机来临" }] },
    },
  });
  const worldviewOutput = worldviewStageOutput({
    artifacts: {
      worldview: { worldview_summary: "资源紧张的近未来都市。" },
    },
  });

  assert.equal(frameworkOutput, "");
  assert.equal(worldviewOutput, "");
});

test("visible stage messages use natural language fields for framework and worldview", () => {
  const messages = visibleStageMessages({
    artifacts: {
      framework_natural_language: "框架自然语言版",
      worldview_natural_language: "世界观自然语言版",
      worldview: { worldview_summary: "不会直接展示" },
    },
    display_stage_key: "worldview",
    display_stage_output_natural: "世界观速览",
  });

  const framework = messages.find((item) => item.key === "framework");
  const worldview = messages.find((item) => item.key === "worldview");

  assert.equal(framework?.output, "框架自然语言版");
  assert.equal(worldview?.output, "世界观自然语言版");
  assert.equal(worldview?.natural, "世界观速览");
});

test("visible stage messages only expose framework worldview and script to ordinary users", () => {
  const messages = visibleStageMessages({
    current_stage: "scenes",
    artifacts: {
      character_natural_language: "人物小传自然语言版",
      character_summary: "{\"should_not\":\"win\"}",
      scene_natural_language: "核心场景自然语言版",
      core_scene_summary: "{\"should_not\":\"win\"}",
    },
    display_stage_key: "scenes",
    display_stage_output_natural: "当前场景速览",
  });

  const characters = messages.find((item) => item.key === "characters");
  const scenes = messages.find((item) => item.key === "scenes");
  const worldview = messages.find((item) => item.key === "worldview");

  assert.equal(characters, undefined);
  assert.equal(scenes, undefined);
  assert.equal(worldview, undefined);
});

test("visible stage messages do not render future-stage placeholders while running", () => {
  const messages = visibleStageMessages({
    status: "running",
    current_stage: "framework",
    artifacts: {},
    display_stage_key: "",
    display_stage_output_natural: "",
  });

  assert.equal(messages.length, 0);
});

test("placeholder strings and object shells are filtered from visible stage messages", () => {
  const messages = visibleStageMessages({
    status: "failed",
    artifacts: {
      framework_natural_language: "剧本框架自然语言说明暂未生成。",
      worldview_natural_language: "{}",
      character_summary: "[object Object]",
      core_scene_summary: "[]",
    },
    display_stage_key: "",
    display_stage_output_natural: "",
  });

  assert.equal(messages.length, 0);
});

test("partial script output formats approved batches before final completion", () => {
  const output = partialScriptOutput({
    artifacts: {
      script_batches_display: [
        { start_episode: 1, end_episode: 5, content: "第1集\n正文 1" },
        { start_episode: 6, end_episode: 10, content: "第6集\n正文 6" },
      ],
    },
  });

  assert.match(output, /第 1-5 集/);
  assert.match(output, /第 6-10 集/);
  assert.equal(output.includes("[object Object]"), false);
});

test("format display value unwraps wrapped multiline script text", () => {
  assert.equal(
    formatDisplayValue({
      content: "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室",
    }),
    "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室",
  );
});

test("partial script output preserves wrapped final script line breaks", () => {
  const output = partialScriptOutput({
    artifacts: {
      final_output_text: {
        content: "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室",
      },
    },
  });

  assert.equal(output, "第1集\n场景1：旧码头\n林夏：先查人。\n\n场景2：会议室");
});

test("status note falls back to runtime stage message with loading dots", () => {
  const note = statusNoteFrom({
    status: "running",
    message: "",
    current_stage: "hook_review",
    current_stage_label: "开头冲突钩子审核",
    current_batch: "1-5",
  }, 1000);

  assert.match(note, /正在审核开头冲突钩子：第 1-5 集\.+/);
});

test("status note stays clear for failed and paused states", () => {
  assert.equal(
    statusNoteFrom({ status: "failed", message: "" }),
    "当前步骤执行失败，可继续或重试。",
  );
  assert.equal(
    statusNoteFrom({ status: "paused", message: "" }),
    "已暂停。",
  );
});

test("running snapshots still expose a live stage-status bubble after earlier outputs exist", () => {
  const thinking = thinkingStateFrom({
    status: "running",
    current_stage: "script_review",
    current_stage_label: "剧本正文审核",
    current_batch: "6-10",
    artifacts: {
      framework_natural_language: "框架自然语言版",
      script_batches_display: [
        { start_episode: 1, end_episode: 5, content: "第1集\n正文 1" },
      ],
    },
  });

  assert.equal(thinking?.stateLabel, "创作中");
  assert.match(thinking?.content || "", /正在审核剧本正文：第 6-10 集/);
});

test("thinking bubble copy text includes the visible runtime message and note", () => {
  const text = thinkingMessageCopyText({
    status: "running",
    current_stage: "script_review",
    current_stage_label: "剧本正文审核",
    current_batch: "6-10",
    message: "",
    artifacts: {
      framework_natural_language: "框架自然语言版",
    },
    runtime_state: {
      message: "正在审核剧本正文：第 6-10 集",
    },
  });

  assert.match(text, /正在审核剧本正文：第 6-10 集/);
});

test("copy button label uses Chinese copy text", () => {
  assert.match(renderCopyButton("user_prompt", "current"), />复制<\/button>/);
});

test("user prompt bubble renders copy in bottom meta row with counts", () => {
  const html = renderUserPromptBubble({
    project_id: 12,
    input_payload: {
      user_expectation: "写一个关于职场逆袭的短剧。",
      character_count: 7,
      total_episodes: 15,
    },
  });

  assert.match(html, /chat-bubble-foot/);
  assert.match(html, /角色数量 7/);
  assert.match(html, /总集数 15/);
  assert.match(html, />复制<\/button>/);
  assert.doesNotMatch(html, /chat-bubble-head-actions/);
});

test("assistant stage bubble renders copy in footer instead of header", () => {
  const html = renderAssistantStageBubble({
    key: "framework",
    title: "剧本框架",
    output: "这是阶段输出。",
    natural: "这是阶段说明。",
  });
  const head = html.match(/<div class="chat-bubble-head">[\s\S]*?<\/div>/)?.[0] || "";

  assert.match(html, /chat-bubble-foot/);
  assert.match(html, /阶段产出/);
  assert.match(html, />复制<\/button>/);
  assert.doesNotMatch(head, /复制/);
  assert.doesNotMatch(head, /chat-bubble-head-actions/);
});

test("render text helper preserves paragraph gaps with html line breaks", () => {
  assert.equal(
    renderTextWithLineBreaks("第一段\n\n第二段"),
    "第一段<br><br>第二段",
  );
});

test("thinking bubble renders current stage label and copy in footer", () => {
  const html = renderThinkingBubble({
    stageLabel: "剧本正文审核：第 6-10 集",
    stateLabel: "创作中",
    content: "正在审核剧本正文：第 6-10 集",
    note: "",
  });
  const head = html.match(/<div class="chat-bubble-head">[\s\S]*?<\/div>/)?.[0] || "";

  assert.match(html, /chat-bubble-foot/);
  assert.match(html, /剧本正文审核：第 6-10 集/);
  assert.match(html, />复制<\/button>/);
  assert.doesNotMatch(head, /复制/);
  assert.doesNotMatch(head, /chat-bubble-head-actions/);
});

test("flash copy button restores the default Chinese label", () => {
  const button = {
    dataset: {},
    textContent: "复制",
    disabled: false,
  };

  flashCopyButton(button, "已复制");

  assert.equal(button.dataset.originalLabel, "复制");
  assert.equal(button.textContent, "复制");
  assert.equal(button.disabled, false);
});

test("asset cards no longer expose the removed new-page action", () => {
  assert.equal(source.includes('data-action="open-project-page"'), false);
  assert.equal(source.includes("新页面打开"), false);
});
