import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const appJsPath = path.join(__dirname, "..", "app", "web", "static", "app.js");
const source = fs.readFileSync(appJsPath, "utf8");

function extractBetween(startToken, endToken) {
  const start = source.indexOf(startToken);
  assert.notEqual(start, -1, `missing token: ${startToken}`);
  const end = source.indexOf(endToken, start);
  assert.notEqual(end, -1, `missing token: ${endToken}`);
  return source.slice(start, end).trim();
}

const bootstrap = [
  'const RUNNING_STATUSES = new Set(["pending", "running", "pausing"]);',
  extractBetween("function normalizeStageKey(stageKey) {", "\n\n  function formatDisplayValue(value) {"),
  extractBetween("function formatDisplayValue(value) {", "\n\n  // 把框架阶段的多个正式产物拼成一个完整回复，方便在聊天流里整体展示。"),
  extractBetween("function runtimeLoadingSuffix(snapshot, nowMs = Date.now()) {", "\n\n  function defaultRuntimeMessage(snapshot) {"),
  extractBetween("function defaultRuntimeMessage(snapshot) {", "\n\n  // 当前状态下只保留必要提示，避免和“当前阶段”重复。"),
  extractBetween("function statusNoteFrom(snapshot, nowMs = Date.now()) {", "\n\n  function creationStatusLabel(snapshot) {"),
  extractBetween("function frameworkStageOutput(snapshot) {", "\n\n  function worldviewStageOutput(snapshot) {"),
  extractBetween("function worldviewStageOutput(snapshot) {", "\n\n  // 只把平台真正对外公开的正式阶段产物整理成聊天消息。"),
  extractBetween("function visibleStageMessages(snapshot) {", "\n\n  // 内部阶段统一折叠成“思考分析”，避免把中间工作流细节直接暴露给用户。"),
  "module.exports = { formatDisplayValue, normalizeStageKey, partialScriptOutput, statusNoteFrom, frameworkStageOutput, worldviewStageOutput, visibleStageMessages };",
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
};
vm.runInNewContext(bootstrap, context, { filename: appJsPath });

const {
  statusNoteFrom,
  partialScriptOutput,
  frameworkStageOutput,
  worldviewStageOutput,
  visibleStageMessages,
} = context.module.exports;

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

test("visible stage messages prefer character and scene natural language fields", () => {
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

  assert.equal(characters?.output, "人物小传自然语言版");
  assert.equal(scenes?.output, "核心场景自然语言版");
  assert.equal(scenes?.natural, "当前场景速览");
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
