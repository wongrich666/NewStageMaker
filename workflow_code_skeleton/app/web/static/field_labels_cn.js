(function () {
  const FIELD_LABELS_CN = {
    source_brief: "原文信息提取",
    worldview_plan: "世界观方案",
    character_plan: "人物设定",
    beat_checkpoint_timeline: "三幕十五节拍",
    checkpoint_explanation: "节拍说明",
    character_storylines: "人物故事线",
    storyline_decisions: "故事线处理",
    adaptation_guide: "整体改编指引",
    framework_plan_package: "最终框架策划包",
    validation_report: "校验报告",
    character_emotion_strategy: "人物情绪策略",
    core_setting_adjustments: "核心设定调整",
    hard_constraints_for_script_workflow: "后续剧本硬性约束",
    structure_and_rhythm: "结构与节奏",
    visualization_strategy: "视觉化策略",
    original_retention: "原文保留内容",
    character_relationships: "人物关系",
    character_rules: "人物规则",
    character_system_summary: "人物系统概述",
    main_characters: "主要人物",
    protagonist: "主角",
    antagonist: "反派",
    supporting_characters: "配角",
    emotion_engine: "情绪引擎",
    relationship_map: "关系图谱",
    ready_for_script_workflow: "是否可进入剧本正文阶段",
    ability_or_resource: "能力 / 资源",
    external_goal: "外部目标",
    internal_need: "内在需求",
    forbidden_write: "禁止写法",
    growth_arc: "成长弧线",
    identity: "身份定位",
    role: "角色功能",
    story_function: "故事功能",
    weakness: "弱点",
    relationship_hooks: "关系钩子",
    scene_count: "场景数量",
    selection_principle: "场景选择原则",
    core_scenes: "核心场景",
    scene_id: "场景编号",
    scene_type: "场景类型",
    source_basis: "来源依据",
    visual_anchor: "视觉锚点",
    dramatic_function: "戏剧功能",
    conflict_soil: "冲突土壤",
    common_characters: "常见出场人物",
    usable_episode_range: "可使用集数范围",
    rules_or_limits: "场景规则 / 限制",
    key_props: "关键道具",
    allowed_actions: "允许发生的动作",
    do_not_use_as: "禁止用途",
    continuity_notes: "连续性注意事项",
    scene_usage_notes: "场景使用说明",
    scriptWorldRulesDigest: "世界规则摘要",
    script_world_rules_digest: "世界规则摘要",
    world_type: "世界类型",
    core_rules: "核心规则",
    action_limits: "行动限制",
    danger_sources: "危险来源",
    resource_or_stakes: "资源 / 利害关系",
    power_distribution: "权力分布",
    special_rules: "特殊规则",
    overall_atmosphere: "整体氛围",
    do_not_break_rules: "不可破坏的规则",
    sceneDictionary: "场景字典",
    scene_dictionary: "场景字典",
    appearanceMapping: "角色外观匹配场景",
    appearance_mapping: "角色外观匹配场景",
    allEnrichedEpisodePlan: "完整分集细化方案",
    all_enriched_episode_plan: "完整分集细化方案",
    allEnrichedEpisodePlanText: "完整分集细化文本",
    all_enriched_episode_plan_text: "完整分集细化文本",
    enrichedEpisodePlan: "分集细化方案",
    enrichedEpisodePlanText: "分集细化文本",
    batchCausalConflictPlan: "因果冲突推进计划",
    batchScriptText: "正文及对话",
    batchScriptReview: "正文审核",
    conflictMemory: "因果冲突记忆",
    scriptMemory: "正文记忆",
    title: "标题",
    name: "名称",
    summary: "摘要",
    overview: "概述",
    description: "说明",
    episode: "集数",
    episode_range: "集数范围",
    focus: "重点",
    status: "状态",
    warnings: "提醒",
    issues: "问题",
    passed: "是否通过",
    project_title: "作品标题（兼容字段）",
    source_title: "作品标题",
    target_format: "目标形式",
    season_count: "季数（固定为1）",
    episodes_per_season: "总集数",
    total_episodes: "总集数",
    episode_word_count: "每集字数",
    chars_per_episode: "每集字数",
    user_requirements: "用户要求",
    user_constraints: "限制条件",
    story_outline: "故事梗概",
    source_text: "原文材料",
    source_brief: "原始故事信息提取",
    source_type: "原始材料类型",
    genre: "题材类型",
    tone: "整体基调",
    core_logline: "故事核心",
    protagonist: "主角",
    main_opposition: "主要阻力 / 对立力量",
    core_conflict: "核心冲突",
    must_keep_elements: "必须保留元素",
    forbidden_deviations: "禁止偏离方向",
    available_material_summary: "现有材料摘要",
    missing_information_risks: "缺失信息风险",
    display_text: "可读摘要",
    adaptation_direction: "改编方向",
    key_changes: "本次重点改变",
    style_requirements: "风格要求",
    risk_warnings: "风险提醒",
    hard_requirements: "后续写作硬要求",
    downstream_requirements: "后续写作要求",
    handoff_to_script_workflow: "下游交接说明",
    generation_priorities: "生成优先级",
    hard_constraints: "硬性约束",
    do_not_change: "不可改动",
    risk_flags: "风险提醒",
    recommended_next_action: "推荐下一步",
  };

  const HIDDEN_FIELD_KEYS_CN = new Set([
    "id", "nodeId", "node_id", "moduleName", "module_name", "moduleType", "module_type",
    "moduleLogo", "module_logo", "raw", "debug", "schema", "schema_version", "mapping_version",
    "token", "tokens", "inputTokens", "outputTokens", "totalPoints", "responseData",
    "updateVarResult", "newVariables", "reasoningText", "historyPreview", "choices", "usage",
    "cache", "logs", "_meta", "metadata", "raw_stage_responses", "raw_output", "answerText",
  ]);

  const WORD_LABELS_CN = {
    world: "世界", worldview: "世界观", script: "剧本", rules: "规则", rule: "规则",
    digest: "摘要", core: "核心", character: "人物", characters: "人物", emotion: "情绪",
    strategy: "策略", relationship: "关系", relationships: "关系", map: "图谱",
    scene: "场景", scenes: "场景", visual: "视觉", anchor: "锚点", conflict: "冲突",
    soil: "土壤", goal: "目标", internal: "内在", external: "外部", need: "需求",
    ability: "能力", resource: "资源", growth: "成长", arc: "弧线", function: "功能",
    type: "类型", source: "来源", basis: "依据", notes: "注意事项", continuity: "连续性",
    action: "行动", actions: "动作", limits: "限制", danger: "危险", stakes: "利害关系",
    power: "权力", distribution: "分布", special: "特殊", atmosphere: "氛围",
    overall: "整体", count: "数量", principle: "原则", props: "道具", key: "关键",
    allowed: "允许", forbidden: "禁止", write: "写法", workflow: "工作流",
    hard: "硬性", constraints: "约束", original: "原文", retention: "保留",
    structure: "结构", rhythm: "节奏", summary: "概述", plan: "方案", text: "文本",
    episode: "集数", batch: "批次", review: "审核", memory: "记忆",
  };

  function labelFor(key) {
    const raw = String(key || "").trim();
    if (!raw) return "其他信息";
    if (/[\u4e00-\u9fff]/.test(raw)) return raw;
    if (FIELD_LABELS_CN[raw]) return FIELD_LABELS_CN[raw];
    const spaced = raw.replace(/([a-z])([A-Z])/g, "$1_$2").replace(/[-\s]+/g, "_");
    if (FIELD_LABELS_CN[spaced]) return FIELD_LABELS_CN[spaced];
    const parts = spaced.split("_").filter(Boolean);
    const translated = parts.map((part) => WORD_LABELS_CN[part.toLowerCase()] || "").filter(Boolean);
    if (translated.length) return translated.join(" / ");
    return "其他信息";
  }

  function isHiddenKey(key) {
    const raw = String(key || "").trim();
    return HIDDEN_FIELD_KEYS_CN.has(raw) || /token|debug|schema|response|raw|module|node/i.test(raw);
  }

  function scalarText(value) {
    if (value === null || value === undefined || value === "") return "暂无";
    if (typeof value === "boolean") return value ? "是" : "否";
    const text = String(value).replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
    return text || "暂无";
  }

  function readableText(value, options) {
    const indent = Number(options && options.indent || 0);
    const pad = " ".repeat(Math.max(0, indent));
    if (value === null || value === undefined || value === "") return "暂无";
    if (typeof value === "string") {
      const text = value.trim();
      if (/^[\[{]/.test(text)) {
        try {
          const parsed = JSON.parse(text);
          if (parsed && typeof parsed === "object") return readableText(parsed, options);
        } catch (error) {}
      }
      return scalarText(value);
    }
    if (typeof value !== "object") return scalarText(value);
    if (Array.isArray(value)) {
      if (!value.length) return "暂无";
      return value.map((item, index) => {
        const prefix = `${pad}${index + 1}. `;
        if (item && typeof item === "object") {
          const nested = readableText(item, { indent: indent + 2 });
          return `${prefix}${nested === "暂无" ? "暂无" : `\n${nested}`}`;
        }
        return `${prefix}${scalarText(item)}`;
      }).join("\n");
    }
    const entries = Object.entries(value).filter(([key, item]) => !isHiddenKey(key) && item !== undefined && item !== null && item !== "");
    if (!entries.length) return "暂无";
    return entries.map(([key, item]) => {
      const label = labelFor(key);
      if (item && typeof item === "object") {
        return `${pad}${label}：\n${readableText(item, { indent: indent + 2 })}`;
      }
      return `${pad}${label}：${scalarText(item)}`;
    }).join("\n");
  }

  window.FIELD_LABELS_CN = FIELD_LABELS_CN;
  window.fieldLabelsCn = { labelFor, readableText, isHiddenKey, scalarText };
})();
