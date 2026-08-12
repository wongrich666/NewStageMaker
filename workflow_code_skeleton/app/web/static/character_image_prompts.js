(() => {
  "use strict";

  const config = window.CHARACTER_IMAGE_PROMPT_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const els = {
    asset: $("cipAsset"), character: $("cipCharacter"), outfit: $("cipOutfit"),
    requirements: $("cipRequirements"), count: $("cipCount"), generate: $("cipGenerate"),
    status: $("cipStatus"), sourceBadges: $("cipSourceBadges"), preview: $("cipCharacterPreview"),
    previewName: $("cipPreviewName"), previewFacts: $("cipPreviewFacts"), loading: $("cipLoading"),
    result: $("cipResult"), resultTitle: $("cipResultTitle"), designSummary: $("cipDesignSummary"),
    positive: $("cipPositivePrompt"), negative: $("cipNegativePrompt"), continuity: $("cipContinuity"),
    viewsPanel: $("cipViewsPanel"), views: $("cipViews"), sourceSummary: $("cipSourceSummary"),
    copyAll: $("cipCopyAll")
  };
  let catalog = null;
  let latestResult = null;

  const apiUrl = (path) => {
    const url = new URL(path, window.location.origin);
    const token = new URLSearchParams(window.location.search).get("auth_token") || config.authToken || "";
    if (token) url.searchParams.set("auth_token", token);
    return url.toString();
  };

  async function requestApi(path, options = {}) {
    const response = await fetch(apiUrl(path), {
      credentials: "same-origin",
      headers: { "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      ...options
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) throw new Error(payload.message || `请求失败（HTTP ${response.status}）`);
    return payload;
  }

  const setStatus = (message, kind = "") => {
    els.status.textContent = message;
    els.status.className = `cip-status${kind ? ` ${kind}` : ""}`;
  };

  const clearOptions = (select, placeholder) => {
    select.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.append(option);
  };

  const addOption = (select, value, label) => {
    const option = document.createElement("option");
    option.value = String(value || "");
    option.textContent = String(label || value || "未命名");
    select.append(option);
  };

  const text = (value, fallback = "—") => {
    if (value === null || value === undefined || value === "") return fallback;
    if (Array.isArray(value)) return value.length ? value.join("、") : fallback;
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  };

  const fact = (label, value) => {
    const wrapper = document.createElement("div");
    const name = document.createElement("span");
    const body = document.createElement("p");
    name.textContent = label;
    body.textContent = text(value);
    wrapper.append(name, body);
    return wrapper;
  };

  function renderSourceBadges(status) {
    const labels = {
      has_character_plan: "03 人物原设", has_scene_dictionary: "08 场景道具",
      has_appearance_mapping: "09 服饰映射", has_episode_plan: "10 分集引用",
      has_script_text: "12 剧本道具"
    };
    els.sourceBadges.replaceChildren();
    Object.entries(labels).forEach(([key, label]) => {
      const badge = document.createElement("span");
      badge.textContent = `${status && status[key] ? "已读取" : "缺少"} · ${label}`;
      if (!status || !status[key]) badge.classList.add("missing");
      els.sourceBadges.append(badge);
    });
  }

  function selectedCharacter() {
    if (!catalog || !Array.isArray(catalog.characters)) return null;
    return catalog.characters.find((item) => String(item.character_id) === els.character.value) || null;
  }

  function renderCharacter() {
    const character = selectedCharacter();
    clearOptions(els.outfit, "自动选择默认服饰");
    if (!character) {
      els.outfit.disabled = true;
      els.preview.classList.add("hidden");
      els.generate.disabled = true;
      return;
    }
    (character.outfits || []).forEach((item) => {
      const range = item.episode_range ? ` · ${item.episode_range}` : "";
      addOption(els.outfit, item.outfit_id, `${item.outfit_name || item.outfit_id}${range}`);
    });
    els.outfit.disabled = !(character.outfits || []).length;
    if ((character.outfits || []).length) els.outfit.value = character.outfits[0].outfit_id;
    els.previewName.textContent = character.character_name || "角色资料";
    els.previewFacts.replaceChildren(
      fact("身份", character.identity),
      fact("角色定位", character.role_type),
      fact("外形锚点", character.appearance_anchor),
      fact("服饰版本", `${(character.outfits || []).length} 个`),
      fact("人物原设", character.source_status && character.source_status.has_original_profile ? "已关联" : "未找到"),
      fact("服饰映射", character.source_status && character.source_status.has_appearance_mapping ? "已关联" : "未找到")
    );
    els.preview.classList.remove("hidden");
    els.generate.disabled = false;
    setStatus(`已选择角色“${character.character_name}”，可以补充形象要求后生成。`);
  }

  async function loadContext(assetId) {
    catalog = null;
    clearOptions(els.character, "正在解析人物资料…");
    els.character.disabled = true;
    els.outfit.disabled = true;
    els.generate.disabled = true;
    els.preview.classList.add("hidden");
    els.result.classList.add("hidden");
    if (!assetId) {
      renderSourceBadges({});
      clearOptions(els.character, "请先选择资产");
      setStatus("请选择一份框架资产");
      return;
    }
    setStatus("正在从 03、08、09、10、12 阶段提取角色视觉资料…");
    try {
      const payload = await requestApi(`/api/character-image-prompts/context?framework_asset_id=${encodeURIComponent(assetId)}`);
      catalog = payload.catalog || {};
      renderSourceBadges(catalog.source_status || {});
      clearOptions(els.character, "请选择角色");
      (catalog.characters || []).forEach((item) => {
        addOption(els.character, item.character_id, `${item.character_name}${item.role_type ? ` · ${item.role_type}` : ""}`);
      });
      els.character.disabled = !(catalog.characters || []).length;
      if ((catalog.characters || []).length) {
        els.character.value = catalog.characters[0].character_id;
        renderCharacter();
      } else {
        setStatus("该资产没有识别到人物设定。", "error");
      }
    } catch (error) {
      clearOptions(els.character, "人物资料读取失败");
      renderSourceBadges({});
      setStatus(error.message || "人物资料读取失败。", "error");
    }
  }

  async function loadAssets() {
    clearOptions(els.asset, "正在读取资产…");
    els.asset.disabled = true;
    try {
      const payload = await requestApi("/api/framework-assets");
      const assets = (payload.assets || []).filter((item) => item.can_import !== false);
      clearOptions(els.asset, assets.length ? "请选择框架资产" : "暂无可用框架资产");
      assets.forEach((item) => addOption(els.asset, item.asset_id, `${item.title} · #${item.asset_id}`));
      els.asset.disabled = !assets.length;
      const requested = new URLSearchParams(window.location.search).get("framework_asset_id") || "";
      const preferred = assets.find((item) => String(item.asset_id) === requested) || assets[0];
      if (preferred) {
        els.asset.value = String(preferred.asset_id);
        await loadContext(els.asset.value);
      } else {
        setStatus("暂无可用框架资产，请先完成框架策划。", "error");
      }
    } catch (error) {
      clearOptions(els.asset, "资产读取失败");
      setStatus(error.message || "资产读取失败。", "error");
    }
  }

  const lockSection = (title, values) => {
    const section = document.createElement("section");
    const heading = document.createElement("h4");
    const list = document.createElement("ul");
    heading.textContent = title;
    const items = Array.isArray(values) && values.length ? values : ["工作流未单独列出"];
    items.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = String(value);
      list.append(item);
    });
    section.append(heading, list);
    return section;
  };

  function renderResult(payload) {
    latestResult = payload.result || {};
    const summary = payload.source_summary || {};
    els.resultTitle.textContent = `${latestResult.character_name || "角色"} · 出图提示词`;
    els.designSummary.textContent = text(latestResult.design_summary);
    els.positive.textContent = text(latestResult.positive_prompt, "");
    els.negative.textContent = text(latestResult.negative_prompt, "");
    const lock = latestResult.continuity_lock || {};
    els.continuity.replaceChildren(
      lockSection("不可漂移特征", lock.immutable_features),
      lockSection("本服饰固定特征", lock.outfit_features),
      lockSection("禁止偏移", lock.forbidden_drift)
    );
    els.views.replaceChildren();
    (latestResult.recommended_views || []).forEach((item) => {
      const card = document.createElement("article");
      const heading = document.createElement("strong");
      const body = document.createElement("p");
      heading.textContent = item.view_type || "补充视图";
      body.textContent = item.prompt_suffix || "";
      card.append(heading, body);
      els.views.append(card);
    });
    els.viewsPanel.classList.toggle("hidden", !(latestResult.recommended_views || []).length);
    const lengths = summary.input_char_lengths || {};
    els.sourceSummary.replaceChildren(
      fact("角色", summary.character && summary.character.character_name),
      fact("服饰", summary.selected_outfit && summary.selected_outfit.outfit_name),
      fact("相关场景", summary.related_scene_count),
      fact("分集证据", summary.related_episode_count),
      fact("道具条目", summary.prop_count),
      fact("送入工作流字符数", Object.values(lengths).reduce((sum, value) => sum + Number(value || 0), 0))
    );
    els.result.classList.remove("hidden");
    requestAnimationFrame(() => els.result.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  async function generate() {
    if (!els.asset.value || !els.character.value) {
      setStatus("请先选择资产和角色。", "error");
      return;
    }
    els.generate.disabled = true;
    els.loading.classList.remove("hidden");
    els.result.classList.add("hidden");
    setStatus("正在调用角色出图提示词工作流…");
    try {
      const payload = await requestApi("/api/character-image-prompts/generate", {
        method: "POST",
        body: JSON.stringify({
          framework_asset_id: els.asset.value,
          character_id: els.character.value,
          selected_outfit_id: els.outfit.value,
          user_visual_requirements: els.requirements.value.trim()
        })
      });
      renderResult(payload);
      setStatus("角色出图提示词已生成，可以直接复制使用。", "success");
    } catch (error) {
      setStatus(error.message || "角色出图提示词生成失败。", "error");
    } finally {
      els.loading.classList.add("hidden");
      els.generate.disabled = !selectedCharacter();
    }
  }

  async function copyText(value, button) {
    const content = String(value || "").trim();
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      const old = button.textContent;
      button.textContent = "已复制";
      setTimeout(() => { button.textContent = old; }, 1200);
    } catch (_) {
      setStatus("浏览器无法访问剪贴板，请手动选择文本复制。", "error");
    }
  }

  els.asset.addEventListener("change", () => loadContext(els.asset.value));
  els.character.addEventListener("change", renderCharacter);
  els.requirements.addEventListener("input", () => {
    els.count.textContent = `${els.requirements.value.length} / 2000 字符`;
  });
  els.generate.addEventListener("click", generate);
  document.querySelectorAll(".cip-copy").forEach((button) => {
    button.addEventListener("click", () => copyText($(button.dataset.copyTarget).textContent, button));
  });
  els.copyAll.addEventListener("click", () => {
    if (!latestResult) return;
    const lock = latestResult.continuity_lock || {};
    const combined = [
      `角色：${latestResult.character_name || ""}`,
      `设计摘要：${latestResult.design_summary || ""}`,
      `正向 Prompt：\n${latestResult.positive_prompt || ""}`,
      `负向 Prompt：\n${latestResult.negative_prompt || ""}`,
      `一致性锁定：\n${[].concat(lock.immutable_features || [], lock.outfit_features || []).join("；")}`
    ].join("\n\n");
    copyText(combined, els.copyAll);
  });

  loadAssets();
})();
