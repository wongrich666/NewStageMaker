from __future__ import annotations

from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
SERVER = ROOT / "workflow_code_skeleton/app/server.py"
FP_JS = ROOT / "workflow_code_skeleton/app/web/static/framework_planner.js"

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")

def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak_framework_generate_script")
    if not bak.exists():
        shutil.copy2(path, bak)

def patch_server() -> None:
    backup(SERVER)
    text = read(SERVER)
    if "/api/framework-planner/generate-script" in text:
        print("[server] endpoint already exists")
        return

    marker = '    @app.post("/api/workflows/start")'
    if marker not in text:
        raise RuntimeError("找不到 /api/workflows/start 插入点，先不要继续。")

    route = r'''
    @app.post("/api/framework-planner/generate-script")
    @_login_required
    def generate_script_from_framework_planner():
        data = request.get_json(silent=True) or {}

        framework_plan_package = data.get("framework_plan_package")
        if not isinstance(framework_plan_package, dict) or not framework_plan_package:
            return _json_error(
                "缺少 framework_plan_package，请先完成并确认 07 最终策划包输出。",
                status=400,
            )

        basic_config = data.get("basic_config") if isinstance(data.get("basic_config"), dict) else {}
        title = (
            str(data.get("title") or "")
            or str(data.get("project_title") or "")
            or str(basic_config.get("project_title") or "")
            or str(basic_config.get("source_title") or "")
            or "未命名框架剧本"
        ).strip()

        def _safe_int(value, default):
            try:
                number = int(value)
                return number if number > 0 else default
            except Exception:
                return default

        total_episodes = _safe_int(
            data.get("total_episodes")
            or data.get("episodes_per_season")
            or basic_config.get("episodes_per_season"),
            60,
        )
        minutes_per_episode = _safe_int(
            data.get("minutes_per_episode") or basic_config.get("minutes_per_episode"),
            2,
        )
        episode_word_count = _safe_int(
            data.get("episode_word_count"),
            max(600, minutes_per_episode * 450),
        )

        expectation_parts = [
            str(data.get("user_expectation") or "").strip(),
            str(data.get("adaptation_direction") or basic_config.get("adaptation_direction") or "").strip(),
            str(data.get("user_requirements") or basic_config.get("user_requirements") or "").strip(),
        ]
        expectation = "\n".join([item for item in expectation_parts if item]).strip()
        if not expectation:
            expectation = f"基于《{title}》的三幕十五节拍框架策划包生成短剧正文。"

        payload = {
            "title": title,
            "project_title": title,
            "source_title": str(data.get("source_title") or basic_config.get("source_title") or title),
            "target_format": str(data.get("target_format") or basic_config.get("target_format") or "短剧"),
            "season_count": _safe_int(data.get("season_count") or basic_config.get("season_count"), 1),
            "episodes_per_season": total_episodes,
            "total_episodes": total_episodes,
            "minutes_per_episode": minutes_per_episode,
            "episode_word_count": episode_word_count,
            "user_expectation": expectation,
            "user_requirements": str(data.get("user_requirements") or basic_config.get("user_requirements") or ""),
            "adaptation_direction": str(data.get("adaptation_direction") or basic_config.get("adaptation_direction") or ""),
            "framework_plan_package": framework_plan_package,
            "source_brief": data.get("source_brief") or framework_plan_package.get("source_brief") or {},
            "worldview_plan": data.get("worldview_plan") or framework_plan_package.get("worldview_plan") or {},
            "character_plan": data.get("character_plan") or framework_plan_package.get("character_plan") or {},
            "beat_checkpoint_timeline": data.get("beat_checkpoint_timeline") or framework_plan_package.get("beat_checkpoint_timeline") or [],
            "checkpoint_explanation": data.get("checkpoint_explanation") or framework_plan_package.get("checkpoint_explanation") or {},
            "character_storylines": data.get("character_storylines") or framework_plan_package.get("character_storylines") or [],
            "storyline_decisions": data.get("storyline_decisions") or framework_plan_package.get("storyline_decisions") or [],
            "adaptation_guide": data.get("adaptation_guide") or framework_plan_package.get("adaptation_guide") or {},
            "workflow_mode": "framework_to_script",
            "generation_chain": "framework_to_script",
            "framework_to_script": True,
            "framework_planner_source": True,
        }

        _attach_user_knowledge_payload(payload, data)

        try:
            snapshot = task_manager.start_task(
                user_id=_require_user_id(),
                input_payload=payload,
                workflow_spec_path=_resolve_spec_path(data),
                model_selection_id=data.get("model_selection_id"),
            )
        except Exception as exc:
            return _json_error(
                str(exc),
                status=400,
                fallback="框架转剧本任务创建失败，请检查新链路 FastGPT API Key 和工作流配置。",
            )

        return _json_ok(task=snapshot)

'''
    text = text.replace(marker, route + "\n" + marker, 1)
    write(SERVER, text)
    print("[server] patched generate-script endpoint")

def patch_framework_planner_js() -> None:
    backup(FP_JS)
    text = read(FP_JS)
    original = text

    # 1. realApi 增加 startFrameworkScript
    if "async startFrameworkScript(payload)" not in text:
        old = """    async runBeatScore(payload) {
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
  };"""
        new = """    async runBeatScore(payload) {
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
    async startFrameworkScript(payload) {
      const response = await fetch(`${API_BASE}/generate-script`, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json().catch(() => ({
        ok: false,
        error: "框架转剧本接口返回了无法解析的响应",
      }));
      if (!response.ok || !data.ok) {
        throw new Error((data && (data.error || data.fallback)) || "框架转剧本任务创建失败");
      }
      return data;
    },
  };"""
        if old not in text:
            raise RuntimeError("找不到 realApi.runBeatScore 片段，无法自动插入 startFrameworkScript。")
        text = text.replace(old, new, 1)

    # 2. mockApi 也补一个兜底，避免 backendReady=false 时报错
    if "async startFrameworkScript(payload)" not in text[text.find("const mockApi = {"):text.find("const planningApi = {")]:
        old = """  const mockApi = {
    async runStage(stage, payload) {
      return buildMockStageResponse(stage, payload || {});
    },
    async runBeatScore(payload) {
      return buildMockScoreResponse(payload || {});
    },
  };"""
        new = """  const mockApi = {
    async runStage(stage, payload) {
      return buildMockStageResponse(stage, payload || {});
    },
    async runBeatScore(payload) {
      return buildMockScoreResponse(payload || {});
    },
    async startFrameworkScript(payload) {
      return {
        ok: true,
        task: {
          project_id: Date.now(),
          task_id: `mock-framework-script-${Date.now()}`,
          status: "running",
          current_stage: "framework_scene_dictionary",
          current_stage_label: "框架转剧本场景字典",
          progress_percent: 1,
          input_payload: payload || {},
        },
      };
    },
  };"""
        if old not in text:
            raise RuntimeError("找不到 mockApi 片段，无法自动插入 startFrameworkScript。")
        text = text.replace(old, new, 1)

    # 3. planningApi 代理 startFrameworkScript
    if "async startFrameworkScript(payload)" not in text[text.find("const planningApi = {"):text.find("const clone =") if "const clone =" in text else len(text)]:
        old = """    async runBeatScore(payload) {
      try {
        return await realApi.runBeatScore(payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runBeatScore(payload);
        }
        throw error;
      }
    },
  };"""
        new = """    async runBeatScore(payload) {
      try {
        return await realApi.runBeatScore(payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.runBeatScore(payload);
        }
        throw error;
      }
    },
    async startFrameworkScript(payload) {
      try {
        return await realApi.startFrameworkScript(payload);
      } catch (error) {
        if (!config.backendReady) {
          return mockApi.startFrameworkScript(payload);
        }
        throw error;
      }
    },
  };"""
        if old not in text:
            raise RuntimeError("找不到 planningApi.runBeatScore 片段，无法自动插入 startFrameworkScript。")
        text = text.replace(old, new, 1)

    # 4. 增加 payload 构造和启动函数，放在 attachKnowledgePayload 后面
    if "function frameworkToScriptPayload()" not in text:
        marker = """  function attachKnowledgePayload(payload, stageKey) {
    return Object.assign({}, payload || {}, knowledgePayloadFields(stageKey || "basic"));
  }
"""
        insert = r'''
  function frameworkToScriptPayload() {
    const basic = state.basic_config || {};
    const frameworkPackage = state.framework_plan_package || {};
    const totalEpisodes = Number(
      basic.episodes_per_season
      || (frameworkPackage.basic_config || {}).episodes_per_season
      || 0
    ) || 60;
    const minutesPerEpisode = Number(
      basic.minutes_per_episode
      || (frameworkPackage.basic_config || {}).minutes_per_episode
      || 2
    ) || 2;
    const title = String(
      basic.project_title
      || basic.source_title
      || (frameworkPackage.basic_config || {}).project_title
      || (frameworkPackage.basic_config || {}).source_title
      || "未命名框架剧本"
    ).trim();

    return attachKnowledgePayload({
      title,
      project_title: title,
      source_title: String(basic.source_title || title),
      target_format: String(basic.target_format || "短剧"),
      season_count: Number(basic.season_count || 1) || 1,
      episodes_per_season: totalEpisodes,
      total_episodes: totalEpisodes,
      minutes_per_episode: minutesPerEpisode,
      episode_word_count: Math.max(600, minutesPerEpisode * 450),
      user_expectation: [
        String(basic.user_requirements || "").trim(),
        String(basic.adaptation_direction || "").trim(),
        String((state.prompt_preferences || {}).script_preference || "").trim(),
      ].filter(Boolean).join("\n"),
      user_requirements: String(basic.user_requirements || ""),
      adaptation_direction: String(basic.adaptation_direction || ""),
      framework_plan_package: frameworkPackage,
      source_brief: state.source_brief || frameworkPackage.source_brief || {},
      worldview_plan: state.worldview_plan || frameworkPackage.worldview_plan || {},
      character_plan: state.character_plan || frameworkPackage.character_plan || {},
      beat_checkpoint_timeline: state.beat_checkpoint_timeline || frameworkPackage.beat_checkpoint_timeline || [],
      checkpoint_explanation: state.checkpoint_explanation || frameworkPackage.checkpoint_explanation || {},
      character_storylines: state.character_storylines || frameworkPackage.character_storylines || [],
      storyline_decisions: state.storyline_decisions || frameworkPackage.storyline_decisions || [],
      adaptation_guide: state.adaptation_guide || frameworkPackage.adaptation_guide || {},
      workflow_mode: "framework_to_script",
      generation_chain: "framework_to_script",
      framework_to_script: true,
      framework_planner_source: true,
    }, "package");
  }

  async function startFrameworkToScriptGeneration() {
    if (isEmptyValue(state.framework_plan_package)) {
      showToast("请先完成并确认 07 最终策划包输出");
      return;
    }
    const proceed = window.confirm("确认使用当前最终策划包进入下游剧本生成吗？系统会自动执行场景字典、人设服装 alias、丰富分集计划、因果冲突和正文对白融合。");
    if (!proceed) return;

    ui.loading.framework_to_script = true;
    render();

    try {
      const data = await planningApi.startFrameworkScript(frameworkToScriptPayload());
      showToast("已创建框架转剧本任务，正在进入主工作台查看进度");
      const task = data.task || {};
      const projectId = task.project_id || "";
      const workspaceUrl = config.workspaceUrl || "/workspace";
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      window.location.href = `${workspaceUrl}${suffix}`;
    } catch (error) {
      showToast(error.message || "框架转剧本任务创建失败");
    } finally {
      ui.loading.framework_to_script = false;
      render();
    }
  }

'''
        if marker not in text:
            raise RuntimeError("找不到 attachKnowledgePayload 插入点。")
        text = text.replace(marker, marker + insert, 1)

    # 5. 给 topbar 增加按钮
    if 'data-action="generate-framework-script"' not in text:
        old = """          <button class="fp-btn small primary" data-action="open-new-script">新建剧本</button>
          <button class="fp-btn small" data-action="toggle-assets">${ui.assetsOpen ? "收起资产" : "查看和管理资产"}</button>"""
        new = """          <button class="fp-btn small primary" data-action="open-new-script">新建剧本</button>
          <button class="fp-btn small primary" data-action="generate-framework-script" ${isEmptyValue(state.framework_plan_package) ? "disabled" : ""}>用当前框架生成剧本</button>
          <button class="fp-btn small" data-action="toggle-assets">${ui.assetsOpen ? "收起资产" : "查看和管理资产"}</button>"""
        if old not in text:
            raise RuntimeError("找不到 topbar 按钮片段，无法插入生成剧本按钮。")
        text = text.replace(old, new, 1)

    # 6. 独立点击监听，避免依赖原有 switch 是否支持新 action
    if "generate-framework-script delegated handler" not in text:
        marker = "  render();\n})();"
        handler = r'''
  // generate-framework-script delegated handler
  app.addEventListener("click", (event) => {
    const target = event.target && event.target.closest
      ? event.target.closest('[data-action="generate-framework-script"]')
      : null;
    if (!target || target.disabled) return;
    event.preventDefault();
    startFrameworkToScriptGeneration();
  });

'''
        if marker not in text:
            raise RuntimeError("找不到文件末尾 render(); 插入点。")
        text = text.replace(marker, handler + marker, 1)

    if text != original:
        write(FP_JS, text)
        print("[framework_planner.js] patched")
    else:
        print("[framework_planner.js] no change")

patch_server()
patch_framework_planner_js()
print("DONE")
