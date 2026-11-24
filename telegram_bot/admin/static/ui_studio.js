/* ==========================================================================
   TelegramBot UI Studio
   - Server-Persisted Appearance & Wallpaper Engine + Ambient Motion & Parallax
   - Muvyo-Style Sidebar Arrange Studio (Drag-and-Drop Groups & Pool)
   - Full-App Summary Hub & Glass Modal Card Editor Promotion Engine
   ========================================================================== */
(() => {
  "use strict";

  const UI_PREFS_CACHE_KEY = "telegrambot.admin.uiPrefs.v1";

  const WALLPAPER_PRESETS = [
    {
      id: "warm-dusk",
      name: "暖暮绯红",
      desc: "玫瑰木与暖琥珀，Muvyo 同源温润质感",
      thumb: "radial-gradient(circle at 24% 22%, rgba(192,99,89,.68), transparent 58%), radial-gradient(circle at 82% 30%, rgba(212,146,86,.44), transparent 55%), linear-gradient(135deg, #161111, #241918)",
    },
    {
      id: "aurora-night",
      name: "夜航极光",
      desc: "苔玉与雾蓝交织的静谧夜幕",
      thumb: "radial-gradient(circle at 20% 20%, rgba(76,159,130,.58), transparent 55%), radial-gradient(circle at 82% 24%, rgba(95,160,204,.50), transparent 55%), linear-gradient(135deg, #0d1216, #141b26)",
    },
    {
      id: "deep-ocean",
      name: "深海琉璃",
      desc: "静谧午夜蓝与冰青流光层叠",
      thumb: "radial-gradient(circle at 18% 78%, rgba(14,165,233,.65), transparent 55%), radial-gradient(circle at 82% 18%, rgba(6,182,212,.55), transparent 55%), linear-gradient(145deg, #07111e, #0d2238)",
    },
    {
      id: "starlight-violet",
      name: "星云紫罗兰",
      desc: "星河紫韵与柔靛微光氛围",
      thumb: "radial-gradient(circle at 24% 24%, rgba(168,85,247,.62), transparent 56%), radial-gradient(circle at 80% 76%, rgba(236,72,153,.45), transparent 55%), linear-gradient(135deg, #110b1c, #1d1431)",
    },
    {
      id: "mist-jade",
      name: "雾岚冷玉",
      desc: "清透青瓷与林雾柔光层次",
      thumb: "radial-gradient(circle at 28% 24%, rgba(52,211,153,.58), transparent 56%), radial-gradient(circle at 78% 78%, rgba(20,184,166,.5), transparent 56%), linear-gradient(140deg, #0b1615, #142b28)",
    },
    {
      id: "frost-silver",
      name: "暮雪银灰",
      desc: "冷调银雾，深浅模式皆通透",
      thumb: "radial-gradient(circle at 22% 20%, rgba(203,213,225,.42), transparent 58%), radial-gradient(circle at 80% 80%, rgba(148,163,184,.36), transparent 58%), linear-gradient(140deg, #161a22, #252b38)",
    },
    {
      id: "minimal-obsidian",
      name: "纯净点阵",
      desc: "低干扰极简微光画布",
      thumb: "radial-gradient(circle at 20% 0%, rgba(148,163,184,.28), transparent 60%), linear-gradient(135deg, #101216, #181c22)",
    },
    {
      id: "none",
      name: "无背景图",
      desc: "纯色底面，保留清爽半透明层级",
      thumb: "linear-gradient(135deg, #151416, #1c1b1f)",
    },
  ];

  const FEATURE_CATALOG = [
    { id: "dashboard", label: "仪表盘", icon: "dashboard", category: "总览" },
    { id: "modules", label: "功能模块", icon: "modules", category: "总览" },
    { id: "moduleRedPacket", label: "自动抢红包", icon: "red_packet", category: "互动与红包", moduleId: "red_packet" },
    { id: "moduleSendRedPacket", label: "发红包", icon: "send_red_packet", category: "互动与红包", moduleId: "send_red_packet" },
    { id: "moduleChatGames", label: "聊天小游戏", icon: "chat_games", category: "互动与红包", moduleId: "chat_games" },
    { id: "moduleAiReply", label: "AI 自动回复", icon: "ai_reply", category: "AI 能力", moduleId: "ai_reply" },
    { id: "moduleUserProfile", label: "群友画像", icon: "user_profile", category: "AI 能力", moduleId: "user_profile" },
    { id: "moduleAiImage", label: "AI 生图", icon: "ai_image", category: "AI 能力", moduleId: "ai_image" },
    { id: "moduleAiDecrypt", label: "AI 解密", icon: "ai_decrypt", category: "AI 能力", moduleId: "ai_decrypt" },
    { id: "moduleGif", label: "GIF动图", icon: "gif", category: "媒体与效率", moduleId: "gif" },
    { id: "moduleWordCloud", label: "词云", icon: "word_cloud", category: "媒体与效率", moduleId: "word_cloud" },
    { id: "moduleQuote", label: "语录贴纸", icon: "quote", category: "媒体与效率", moduleId: "quote" },
    { id: "moduleCheckin", label: "自动签到", icon: "checkin", category: "媒体与效率", moduleId: "checkin" },
    { id: "moduleAutoForward", label: "自动转发", icon: "auto_forward", category: "媒体与效率", moduleId: "auto_forward" },
    { id: "moduleMagnetImport", label: "磁力数据导入", icon: "magnet_import", category: "同步与导入", moduleId: "magnet_import" },
    { id: "moduleRexWidgetSync", label: "Rex 模块同步", icon: "rex_widget_sync", category: "同步与导入", moduleId: "rex_widget_sync" },
    { id: "sidebarArrange", label: "编排", icon: "arrange", category: "设置中心" },
    { id: "settings", label: "系统配置", icon: "settings", category: "设置中心" },
    { id: "aiServices", label: "AI 服务", icon: "aiServices", category: "设置中心" },
    { id: "aiUsage", label: "AI 用量", icon: "aiUsage", category: "设置中心" },
  ];

  const FEATURE_BY_ID = new Map(FEATURE_CATALOG.map((item) => [item.id, item]));

  function defaultSidebarLayout() {
    return [
      { id: "g_overview", title: "仪表盘", items: ["dashboard", "modules"] },
      { id: "g_interactive", title: "互动与红包", items: ["moduleRedPacket", "moduleSendRedPacket", "moduleChatGames"] },
      { id: "g_ai", title: "AI 能力", items: ["moduleAiReply", "moduleUserProfile", "moduleAiImage", "moduleAiDecrypt"] },
      { id: "g_media", title: "媒体与效率", items: ["moduleGif", "moduleWordCloud", "moduleQuote", "moduleCheckin", "moduleAutoForward"] },
      { id: "g_sync", title: "同步与导入", items: ["moduleMagnetImport", "moduleRexWidgetSync"] },
      { id: "g_system", title: "设置中心", items: ["sidebarArrange", "settings", "aiServices", "aiUsage"] },
    ];
  }

  function recommendedSidebarLayout() {
    return [
      { id: "g_overview", title: "仪表盘", items: ["dashboard", "modules"] },
      { id: "g_hot", title: "常用模块", items: ["moduleRedPacket", "moduleAiReply", "moduleCheckin", "moduleUserProfile"] },
      { id: "g_ai_cfg", title: "AI 配置", items: ["aiServices", "aiUsage"] },
      { id: "g_system", title: "设置中心", items: ["sidebarArrange", "settings"] },
    ];
  }

  function defaultAppearance() {
    return {
      accent: "crimson",
      wallpaperType: "preset",
      wallpaperPreset: "warm-dusk",
      wallpaperUrl: "",
      skinId: "",
      showSkinAvatar: true,
      wallpaperOpacity: 68,
      glassOpacity: 56,
      glassBlur: 18,
      ambientEffect: "aurora",
      mouseParallax: true,
      cardSpotlight: true,
    };
  }

  const studioState = {
    prefs: {
      version: 1,
      theme: document.documentElement.dataset.theme || "dark",
      density: document.documentElement.dataset.density || "comfortable",
      sidebarCollapsed: document.documentElement.dataset.sidebar === "collapsed",
      appearance: defaultAppearance(),
      sidebarLayout: defaultSidebarLayout(),
      wallpapers: [],
      skins: [],
    },
    hasCustomSidebarLayout: false,
    prefsRevision: 0,
    pendingSidebarSave: false,
    saveTimer: null,
    activeModal: null, // { cardEl, viewId, ancestors, stickyAncestors, tabPane, saveBtnId }
    arrangeSearch: "",
    openMoveMenuKey: null,
    dragPayload: null,
  };

  /* ========================================================================
     1. Preferences Persistence & Sync
     ======================================================================== */

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function layoutsEqual(a, b) {
    try {
      return JSON.stringify(normalizeLayout(a)) === JSON.stringify(normalizeLayout(b));
    } catch (_err) {
      return false;
    }
  }

  function setArrangeSaveStatus(kind, text) {
    const el = document.getElementById("arrangeSaveStatus");
    if (!el) return;
    el.dataset.state = kind || "saved";
    el.textContent = text;
  }

  function normalizeLayout(raw) {
    if (!Array.isArray(raw) || !raw.length) return defaultSidebarLayout();
    const seen = new Set();
    const result = [];
    raw.forEach((group, idx) => {
      if (!group || typeof group !== "object") return;
      const items = [];
      if (Array.isArray(group.items)) {
        group.items.forEach((id) => {
          if (FEATURE_BY_ID.has(id) && !seen.has(id)) {
            seen.add(id);
            items.push(id);
          }
        });
      }
      result.push({
        id: String(group.id || `group_${idx + 1}`),
        title: String(group.title ?? ""),
        items,
      });
    });
    return result.length ? result : defaultSidebarLayout();
  }

  function mergePrefs(incoming, { preserveSidebar = false } = {}) {
    if (!incoming || typeof incoming !== "object") return;
    if (incoming.theme === "dark" || incoming.theme === "light") {
      studioState.prefs.theme = incoming.theme;
    }
    if (["compact", "comfortable", "spacious"].includes(incoming.density)) {
      studioState.prefs.density = incoming.density;
    }
    if (typeof incoming.sidebarCollapsed === "boolean") {
      studioState.prefs.sidebarCollapsed = incoming.sidebarCollapsed;
    }
    if (incoming.appearance && typeof incoming.appearance === "object") {
      studioState.prefs.appearance = {
        ...defaultAppearance(),
        ...studioState.prefs.appearance,
        ...incoming.appearance,
      };
    }
    if (!preserveSidebar && incoming.sidebarLayout !== undefined) {
      if (Array.isArray(incoming.sidebarLayout) && incoming.sidebarLayout.length) {
        studioState.prefs.sidebarLayout = normalizeLayout(incoming.sidebarLayout);
        studioState.hasCustomSidebarLayout = true;
      } else if (incoming.sidebarLayout === null && !studioState.hasCustomSidebarLayout) {
        studioState.prefs.sidebarLayout = defaultSidebarLayout();
      }
    }
    if (Array.isArray(incoming.wallpapers)) {
      studioState.prefs.wallpapers = incoming.wallpapers;
    }
    if (Array.isArray(incoming.skins)) {
      studioState.prefs.skins = incoming.skins;
    }
  }

  function cachePrefsLocally() {
    try {
      const payload = {
        theme: studioState.prefs.theme,
        density: studioState.prefs.density,
        sidebarCollapsed: studioState.prefs.sidebarCollapsed,
        appearance: studioState.prefs.appearance,
        sidebarLayout: studioState.prefs.sidebarLayout,
        hasCustomSidebarLayout: studioState.hasCustomSidebarLayout,
        skins: studioState.prefs.skins,
      };
      localStorage.setItem(UI_PREFS_CACHE_KEY, JSON.stringify(payload));
      localStorage.setItem("telegrambot.admin.theme.v1", studioState.prefs.theme);
      localStorage.setItem("telegrambot.admin.density.v1", studioState.prefs.density);
      localStorage.setItem("telegrambot.admin.sidebar.v1", studioState.prefs.sidebarCollapsed ? "collapsed" : "expanded");
    } catch (_err) {}
  }

  function buildPrefsPatch(includeSidebar = false) {
    const patch = {
      theme: studioState.prefs.theme,
      density: studioState.prefs.density,
      sidebarCollapsed: studioState.prefs.sidebarCollapsed,
      appearance: studioState.prefs.appearance,
    };
    if (includeSidebar || studioState.hasCustomSidebarLayout) {
      patch.sidebarLayout = studioState.prefs.sidebarLayout;
    }
    return patch;
  }

  async function flushPrefsSave({ includeSidebar = false, keepalive = false } = {}) {
    if (studioState.saveTimer) {
      window.clearTimeout(studioState.saveTimer);
      studioState.saveTimer = null;
    }
    const savingSidebar = Boolean(includeSidebar || studioState.pendingSidebarSave);
    studioState.pendingSidebarSave = false;
    const payload = buildPrefsPatch(savingSidebar);
    if (savingSidebar) setArrangeSaveStatus("saving", "保存中…");
    try {
      if (keepalive && typeof fetch === "function") {
        await fetch("/api/ui/preferences", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          keepalive: true,
          body: JSON.stringify(payload),
        });
        if (savingSidebar) setArrangeSaveStatus("saved", "已持久保存至服务器");
        return;
      }
      const res = await putJson("/api/ui/preferences", payload);
      if (res?.preferences) {
        studioState.prefs.wallpapers = res.preferences.wallpapers || studioState.prefs.wallpapers;
        studioState.prefs.skins = res.preferences.skins || studioState.prefs.skins;
        cachePrefsLocally();
      }
      if (savingSidebar) setArrangeSaveStatus("saved", "已持久保存至服务器");
    } catch (_err) {
      if (savingSidebar) {
        studioState.pendingSidebarSave = true;
        setArrangeSaveStatus("error", "服务端保存失败，刷新前请重试");
      }
    }
  }

  function schedulePrefsSave(options = {}) {
    const immediate = Boolean(options?.immediate);
    const includeSidebar = Boolean(options?.includeSidebar);
    studioState.prefsRevision += 1;
    if (includeSidebar) {
      studioState.hasCustomSidebarLayout = true;
      studioState.pendingSidebarSave = true;
      setArrangeSaveStatus("saving", "保存中…");
    }
    cachePrefsLocally();
    if (studioState.saveTimer) {
      window.clearTimeout(studioState.saveTimer);
      studioState.saveTimer = null;
    }
    if (immediate) {
      void flushPrefsSave({ includeSidebar: studioState.pendingSidebarSave });
      return;
    }
    studioState.saveTimer = window.setTimeout(() => {
      studioState.saveTimer = null;
      void flushPrefsSave({ includeSidebar: studioState.pendingSidebarSave });
    }, 180);
  }

  async function hydratePrefs() {
    let localHadCustomLayout = false;
    try {
      const rawCached = localStorage.getItem(UI_PREFS_CACHE_KEY);
      if (rawCached) {
        const cached = JSON.parse(rawCached);
        if (
          cached &&
          Array.isArray(cached.sidebarLayout) &&
          cached.sidebarLayout.length &&
          (cached.hasCustomSidebarLayout === true || !layoutsEqual(cached.sidebarLayout, defaultSidebarLayout()))
        ) {
          localHadCustomLayout = true;
        }
        mergePrefs(cached);
        if (!localHadCustomLayout) studioState.hasCustomSidebarLayout = false;
      }
    } catch (_err) {}
    applyAllPreferences(false);
    const startRevision = studioState.prefsRevision;
    try {
      const remote = await getJson("/api/ui/preferences");
      if (!remote || typeof remote !== "object") return;
      if (studioState.prefsRevision !== startRevision) {
        // User edited preferences while fetching; only refresh media catalogs
        if (Array.isArray(remote.wallpapers)) studioState.prefs.wallpapers = remote.wallpapers;
        if (Array.isArray(remote.skins)) studioState.prefs.skins = remote.skins;
        cachePrefsLocally();
        return;
      }
      const remoteHasLayout = Array.isArray(remote.sidebarLayout) && remote.sidebarLayout.length > 0;
      if (!remoteHasLayout && localHadCustomLayout) {
        mergePrefs(remote, { preserveSidebar: true });
        studioState.hasCustomSidebarLayout = true;
        cachePrefsLocally();
        applyAllPreferences(false);
        void flushPrefsSave({ includeSidebar: true });
        return;
      }
      mergePrefs(remote);
      cachePrefsLocally();
      applyAllPreferences(false);
      if (remoteHasLayout) setArrangeSaveStatus("saved", "已持久保存至服务器");
    } catch (_err) {}
  }

  /* ========================================================================
     2. Appearance Application, .mvskin Palette Engine & Ambient Motion
     ======================================================================== */

  const SKIN_OVERRIDE_PROPS = [
    "--accent",
    "--accent-hover",
    "--accent-ink",
    "--accent-on",
    "--accent-soft",
    "--accent-soft-strong",
    "--accent-border",
    "--accent-rgb",
    "--glass-rgb",
    "--glass-elevated-rgb",
    "--glass-inset-rgb",
    "--bg",
    "--border",
    "--border-strong",
    "--border-subtle",
    "--muted",
    "--faint",
    "--skin-ribbon",
  ];

  function hexToRgb(hex) {
    const clean = String(hex || "").replace("#", "").trim();
    if (!/^[0-9a-fA-F]{6}$/.test(clean)) return [192, 99, 89];
    return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
  }

  function rgbToHsl(r, g, b) {
    const rn = r / 255;
    const gn = g / 255;
    const bn = b / 255;
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    let h = 0;
    let s = 0;
    const l = (max + min) / 2;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      if (max === rn) h = (gn - bn) / d + (gn < bn ? 6 : 0);
      else if (max === gn) h = (bn - rn) / d + 2;
      else h = (rn - gn) / d + 4;
      h *= 60;
    }
    return { h, s: s * 100, l: l * 100 };
  }

  function hslToRgb(h, s, l) {
    const hh = ((h % 360) + 360) % 360;
    const ss = Math.max(0, Math.min(100, s)) / 100;
    const ll = Math.max(0, Math.min(100, l)) / 100;
    const c = (1 - Math.abs(2 * ll - 1)) * ss;
    const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
    const m = ll - c / 2;
    let r = 0;
    let g = 0;
    let b = 0;
    if (hh < 60) [r, g, b] = [c, x, 0];
    else if (hh < 120) [r, g, b] = [x, c, 0];
    else if (hh < 180) [r, g, b] = [0, c, x];
    else if (hh < 240) [r, g, b] = [0, x, c];
    else if (hh < 300) [r, g, b] = [x, 0, c];
    else [r, g, b] = [c, 0, x];
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
  }

  function rgbToHex([r, g, b]) {
    return `#${[r, g, b].map((n) => Math.max(0, Math.min(255, n)).toString(16).padStart(2, "0")).join("")}`;
  }

  function activeCustomSkin() {
    const app = studioState.prefs.appearance;
    if (app.wallpaperType !== "skin" || !app.skinId) return null;
    return (studioState.prefs.skins || []).find((s) => s.id === app.skinId) || null;
  }

  function clearCustomSkinPalette() {
    const root = document.documentElement;
    SKIN_OVERRIDE_PROPS.forEach((prop) => root.style.removeProperty(prop));
  }

  function applyCustomSkinPalette(skin, theme) {
    const root = document.documentElement;
    if (!skin || !Array.isArray(skin.candidates) || !skin.candidates.length) {
      clearCustomSkinPalette();
      return;
    }
    const accentRaw = skin.candidates[skin.accent_index] || skin.candidates[0];
    const secondaryRaw = skin.candidates[skin.secondary_index] || skin.candidates[skin.candidates.length - 1] || accentRaw;
    const baseHsl = rgbToHsl(...hexToRgb(accentRaw));
    const secHsl = rgbToHsl(...hexToRgb(secondaryRaw));

    const hue = baseHsl.h;
    const sat = Math.max(26, Math.min(54, baseHsl.s || 36));
    const surfSat = Math.max(8, Math.min(18, baseHsl.s * 0.45));

    if (theme === "light") {
      const accRgb = hslToRgb(hue, Math.min(54, sat + 6), 44);
      const hovRgb = hslToRgb(hue, Math.min(56, sat + 8), 38);
      const inkRgb = hslToRgb(hue, Math.min(54, sat + 6), 34);
      const bgRgb = hslToRgb(hue, Math.min(14, surfSat), 97);
      const glassRgb = hslToRgb(hue, Math.min(10, surfSat), 99);
      const elevRgb = [255, 255, 255];
      const insetRgb = hslToRgb(hue, Math.min(14, surfSat), 93);
      const mutRgb = hslToRgb(hue, Math.min(22, surfSat + 8), 40);
      const faintRgb = hslToRgb(hue, Math.min(18, surfSat + 4), 56);
      const bdrRgb = hslToRgb(hue, Math.min(26, surfSat + 10), 26);

      root.style.setProperty("--accent", rgbToHex(accRgb));
      root.style.setProperty("--accent-hover", rgbToHex(hovRgb));
      root.style.setProperty("--accent-ink", rgbToHex(inkRgb));
      root.style.setProperty("--accent-on", "#ffffff");
      root.style.setProperty("--accent-rgb", accRgb.join(" "));
      root.style.setProperty("--accent-soft", `rgb(${accRgb.join(" ")} / 0.12)`);
      root.style.setProperty("--accent-soft-strong", `rgb(${accRgb.join(" ")} / 0.2)`);
      root.style.setProperty("--accent-border", `rgb(${accRgb.join(" ")} / 0.32)`);
      root.style.setProperty("--bg", rgbToHex(bgRgb));
      root.style.setProperty("--glass-rgb", glassRgb.join(" "));
      root.style.setProperty("--glass-elevated-rgb", elevRgb.join(" "));
      root.style.setProperty("--glass-inset-rgb", insetRgb.join(" "));
      root.style.setProperty("--muted", rgbToHex(mutRgb));
      root.style.setProperty("--faint", rgbToHex(faintRgb));
      root.style.setProperty("--border", `rgb(${bdrRgb.join(" ")} / 0.12)`);
      root.style.setProperty("--border-strong", `rgb(${bdrRgb.join(" ")} / 0.2)`);
      root.style.setProperty("--border-subtle", `rgb(${bdrRgb.join(" ")} / 0.065)`);
      root.style.setProperty("--skin-ribbon", rgbToHex(hslToRgb(secHsl.h, Math.min(40, secHsl.s), 76)));
    } else {
      const accRgb = hslToRgb(hue, sat, 55);
      const hovRgb = hslToRgb(hue, Math.min(56, sat + 4), 61);
      const inkRgb = hslToRgb(hue, Math.min(54, sat + 6), 74);
      const bgRgb = hslToRgb(hue, surfSat, 6.5);
      const glassRgb = hslToRgb(hue, Math.min(18, surfSat + 2), 11);
      const elevRgb = hslToRgb(hue, Math.min(20, surfSat + 3), 16.5);
      const insetRgb = hslToRgb(hue, surfSat, 7);
      const mutRgb = hslToRgb(hue, Math.min(20, surfSat + 6), 65);
      const faintRgb = hslToRgb(hue, Math.min(16, surfSat + 4), 46);
      const bdrRgb = hslToRgb(hue, Math.min(24, surfSat + 10), 84);

      root.style.setProperty("--accent", rgbToHex(accRgb));
      root.style.setProperty("--accent-hover", rgbToHex(hovRgb));
      root.style.setProperty("--accent-ink", rgbToHex(inkRgb));
      root.style.setProperty("--accent-on", "#fff9f8");
      root.style.setProperty("--accent-rgb", accRgb.join(" "));
      root.style.setProperty("--accent-soft", `rgb(${accRgb.join(" ")} / 0.16)`);
      root.style.setProperty("--accent-soft-strong", `rgb(${accRgb.join(" ")} / 0.26)`);
      root.style.setProperty("--accent-border", `rgb(${accRgb.join(" ")} / 0.36)`);
      root.style.setProperty("--bg", rgbToHex(bgRgb));
      root.style.setProperty("--glass-rgb", glassRgb.join(" "));
      root.style.setProperty("--glass-elevated-rgb", elevRgb.join(" "));
      root.style.setProperty("--glass-inset-rgb", insetRgb.join(" "));
      root.style.setProperty("--muted", rgbToHex(mutRgb));
      root.style.setProperty("--faint", rgbToHex(faintRgb));
      root.style.setProperty("--border", `rgb(${bdrRgb.join(" ")} / 0.13)`);
      root.style.setProperty("--border-strong", `rgb(${bdrRgb.join(" ")} / 0.22)`);
      root.style.setProperty("--border-subtle", `rgb(${bdrRgb.join(" ")} / 0.07)`);
      root.style.setProperty("--skin-ribbon", secondaryRaw);
    }
  }

  function currentWallpaperLabel() {
    const app = studioState.prefs.appearance;
    const skin = activeCustomSkin();
    if (skin) return skin.name;
    if (app.wallpaperType === "none") return "无背景图";
    if (app.wallpaperType === "upload") return "自定义壁纸";
    if (app.wallpaperType === "url" && app.wallpaperUrl) return "在线壁纸";
    const preset = WALLPAPER_PRESETS.find((item) => item.id === app.wallpaperPreset);
    return preset ? preset.name : "暖暮绯红";
  }

  function ambientEffectLabel(effect) {
    return (
      {
        aurora: "极光流动",
        stardust: "轻星尘",
        mesh: "呼吸光网",
        none: "静态纯净",
      }[effect] || "极光流动"
    );
  }

  function syncTopbarSkinAvatar(skin) {
    const btn = document.getElementById("topbarSkinAvatarBtn");
    const img = document.getElementById("topbarSkinAvatarImg");
    if (!btn || !img) return;
    const show = Boolean(skin && studioState.prefs.appearance.showSkinAvatar !== false);
    btn.classList.toggle("hidden", !show);
    if (show) {
      if (img.getAttribute("src") !== skin.avatar_url) {
        img.setAttribute("src", skin.avatar_url);
      }
      img.alt = skin.name;
      btn.title = `${skin.name}${skin.description ? ` · ${skin.description}` : ""}（点击管理皮肤）`;
    }
  }

  function applyAllPreferences(persist = false) {
    const root = document.documentElement;
    const { theme, density, sidebarCollapsed, appearance } = studioState.prefs;

    if (typeof applyTheme === "function" && root.dataset.theme !== theme) {
      applyTheme(theme, false);
    }
    if (typeof applyDensity === "function" && root.dataset.density !== density) {
      applyDensity(density, false);
    }
    if (sidebarCollapsed) root.dataset.sidebar = "collapsed";
    else delete root.dataset.sidebar;

    const skin = activeCustomSkin();
    root.dataset.accent = appearance.accent || "crimson";
    root.dataset.wallpaperType = skin ? "skin" : appearance.wallpaperType === "skin" ? "preset" : appearance.wallpaperType || "preset";
    root.dataset.wallpaperPreset = appearance.wallpaperPreset || "warm-dusk";
    root.dataset.ambient = appearance.ambientEffect || "aurora";
    root.dataset.spotlight = appearance.cardSpotlight ? "on" : "off";

    if (skin) {
      applyCustomSkinPalette(skin, theme);
    } else {
      clearCustomSkinPalette();
    }
    syncTopbarSkinAvatar(skin);

    const wpOpacity = Math.max(0, Math.min(100, Number(appearance.wallpaperOpacity ?? 68)));
    const glassOpacity = Math.max(24, Math.min(90, Number(appearance.glassOpacity ?? 56)));
    const glassBlur = Math.max(0, Math.min(32, Number(appearance.glassBlur ?? 18)));
    root.style.setProperty("--wallpaper-opacity", String(wpOpacity / 100));
    root.style.setProperty("--glass-alpha", String(glassOpacity / 100));
    root.style.setProperty("--glass-blur", `${glassBlur}px`);

    const wpLayer = document.getElementById("wallpaperLayer");
    if (wpLayer) {
      if (skin) {
        wpLayer.style.backgroundImage = `url("${skin.background_url.replace(/"/g, '\\"')}")`;
        const cx = Math.round((skin.avatar?.cx ?? 0.5) * 100);
        const cy = Math.round((skin.avatar?.cy ?? 0.35) * 100);
        wpLayer.style.backgroundPosition = `${cx}% ${Math.max(15, Math.min(60, cy))}%`;
      } else if ((appearance.wallpaperType === "upload" || appearance.wallpaperType === "url") && appearance.wallpaperUrl) {
        wpLayer.style.backgroundImage = `url("${appearance.wallpaperUrl.replace(/"/g, '\\"')}")`;
        wpLayer.style.backgroundPosition = "center";
      } else {
        wpLayer.style.backgroundImage = "";
        wpLayer.style.backgroundPosition = "center";
      }
    }

    if (!appearance.mouseParallax) {
      root.style.setProperty("--parallax-x", "0px");
      root.style.setProperty("--parallax-y", "0px");
    }

    renderSidebarFromLayout();
    updateSettingsStudioBadges();
    syncAppearanceModalControls();
    ambientEngine.syncMode();

    if (typeof drawCharts === "function") {
      window.requestAnimationFrame(() => drawCharts());
    }
    if (persist) schedulePrefsSave();
  }

  const ambientEngine = (() => {
    let canvas = null;
    let ctx = null;
    let rafId = null;
    let width = 0;
    let height = 0;
    let particles = [];
    let pointer = { nx: 0, ny: 0, x: 0.5, y: 0.35, active: false };
    let smooth = { px: 0, py: 0, cx: 0.5, cy: 0.35 };
    const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    function initParticles() {
      particles = Array.from({ length: 48 }, () => ({
        x: Math.random(),
        y: Math.random(),
        vx: (Math.random() - 0.5) * 0.00028,
        vy: -0.00012 - Math.random() * 0.00026,
        r: 1.1 + Math.random() * 2.2,
        phase: Math.random() * Math.PI * 2,
        alpha: 0.25 + Math.random() * 0.55,
      }));
    }

    function resize() {
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      width = Math.max(1, window.innerWidth);
      height = Math.max(1, window.innerHeight);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx = canvas.getContext("2d");
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function accentRgb() {
      const raw = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim() || "20 212 162";
      return raw.split(/\s+/).map((n) => Number(n) || 0);
    }

    function drawFrame(now) {
      rafId = null;
      if (!ctx || document.hidden || reduceMotion()) return;
      const app = studioState.prefs.appearance;
      const mode = app.ambientEffect || "aurora";
      const wantParallax = Boolean(app.mouseParallax);
      const wantSpotlight = Boolean(app.cardSpotlight);

      // Smooth damped pointer interpolation for parallax + cursor glow
      const targetPx = wantParallax ? -pointer.nx * 11 : 0;
      const targetPy = wantParallax ? -pointer.ny * 9 : 0;
      smooth.px += (targetPx - smooth.px) * 0.075;
      smooth.py += (targetPy - smooth.py) * 0.075;
      smooth.cx += (pointer.x - smooth.cx) * 0.12;
      smooth.cy += (pointer.y - smooth.cy) * 0.12;

      if (wantParallax) {
        document.documentElement.style.setProperty("--parallax-x", `${smooth.px.toFixed(2)}px`);
        document.documentElement.style.setProperty("--parallax-y", `${smooth.py.toFixed(2)}px`);
      }
      if (wantSpotlight && pointer.active) {
        document.documentElement.style.setProperty("--cursor-x", `${(smooth.cx * width).toFixed(1)}px`);
        document.documentElement.style.setProperty("--cursor-y", `${(smooth.cy * height).toFixed(1)}px`);
      }

      ctx.clearRect(0, 0, width, height);
      const [ar, ag, ab] = accentRgb();
      const isLight = document.documentElement.dataset.theme === "light";
      const t = now * 0.00042;

      if (mode === "aurora") {
        const blobs = [
          { x: 0.22 + Math.sin(t * 0.9) * 0.12 + pointer.nx * 0.03, y: 0.18 + Math.cos(t * 0.7) * 0.1, r: Math.max(width, height) * 0.38, c: `rgba(${ar},${ag},${ab},${isLight ? 0.13 : 0.16})` },
          { x: 0.78 + Math.cos(t * 0.8) * 0.11 - pointer.nx * 0.025, y: 0.28 + Math.sin(t * 0.65) * 0.12, r: Math.max(width, height) * 0.34, c: `rgba(56,189,248,${isLight ? 0.11 : 0.13})` },
          { x: 0.52 + Math.sin(t * 0.55 + 1.4) * 0.15, y: 0.84 + Math.cos(t * 0.6) * 0.08, r: Math.max(width, height) * 0.32, c: `rgba(168,85,247,${isLight ? 0.08 : 0.1})` },
        ];
        ctx.globalCompositeOperation = isLight ? "source-over" : "lighter";
        blobs.forEach((b) => {
          const g = ctx.createRadialGradient(b.x * width, b.y * height, 0, b.x * width, b.y * height, b.r);
          g.addColorStop(0, b.c);
          g.addColorStop(1, "rgba(0,0,0,0)");
          ctx.fillStyle = g;
          ctx.fillRect(0, 0, width, height);
        });
        ctx.globalCompositeOperation = "source-over";
      } else if (mode === "stardust") {
        const mx = smooth.cx * width;
        const my = smooth.cy * height;
        particles.forEach((p) => {
          p.x += p.vx;
          p.y += p.vy;
          if (p.y < -0.02) {
            p.y = 1.02;
            p.x = Math.random();
          }
          if (p.x < -0.02) p.x = 1.02;
          if (p.x > 1.02) p.x = -0.02;

          let px = p.x * width;
          let py = p.y * height;
          let boost = 0;
          if (pointer.active) {
            const dx = px - mx;
            const dy = py - my;
            const dist = Math.hypot(dx, dy);
            if (dist < 140 && dist > 1) {
              const force = (1 - dist / 140) * 14;
              px += (dx / dist) * force;
              py += (dy / dist) * force;
              boost = (1 - dist / 140) * 0.45;
              ctx.strokeStyle = `rgba(${ar},${ag},${ab},${(1 - dist / 140) * (isLight ? 0.16 : 0.22)})`;
              ctx.lineWidth = 0.8;
              ctx.beginPath();
              ctx.moveTo(mx, my);
              ctx.lineTo(px, py);
              ctx.stroke();
            }
          }
          const twinkle = 0.65 + 0.35 * Math.sin(now * 0.002 + p.phase);
          const alpha = Math.min(0.95, (p.alpha * twinkle + boost) * (isLight ? 0.55 : 0.85));
          ctx.fillStyle = boost > 0.08 ? `rgba(${ar},${ag},${ab},${alpha})` : isLight ? `rgba(40,55,75,${alpha})` : `rgba(244,240,238,${alpha})`;
          ctx.beginPath();
          ctx.arc(px, py, p.r + boost * 1.4, 0, Math.PI * 2);
          ctx.fill();
        });
      } else if (mode === "mesh") {
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${isLight ? 0.12 : 0.14})`;
        ctx.lineWidth = 1;
        const bands = 6;
        for (let b = 0; b < bands; b++) {
          ctx.beginPath();
          const baseY = height * (0.18 + (b / (bands - 1)) * 0.66);
          for (let x = 0; x <= width; x += 28) {
            const wave =
              Math.sin(x * 0.0032 + t * 2.1 + b * 0.85) * 26 +
              Math.cos(x * 0.0018 - t * 1.4 + b) * 16 +
              pointer.ny * 14;
            if (x === 0) ctx.moveTo(x, baseY + wave);
            else ctx.lineTo(x, baseY + wave);
          }
          ctx.stroke();
        }
      }

      if (mode !== "none" || wantParallax) {
        rafId = window.requestAnimationFrame(drawFrame);
      }
    }

    function syncMode() {
      if (!canvas) return;
      const app = studioState.prefs.appearance;
      const shouldRun = !document.hidden && !reduceMotion() && (app.ambientEffect !== "none" || app.mouseParallax);
      if (!shouldRun) {
        if (rafId) {
          window.cancelAnimationFrame(rafId);
          rafId = null;
        }
        if (ctx) ctx.clearRect(0, 0, width, height);
        return;
      }
      if (!rafId) rafId = window.requestAnimationFrame(drawFrame);
    }

    function init() {
      canvas = document.getElementById("ambientCanvas");
      if (!canvas) return;
      initParticles();
      resize();
      window.addEventListener("resize", resize);
      document.addEventListener("visibilitychange", syncMode);

      window.addEventListener(
        "pointermove",
        (event) => {
          if (width <= 0 || height <= 0) return;
          pointer.active = true;
          pointer.x = event.clientX / width;
          pointer.y = event.clientY / height;
          pointer.nx = (pointer.x - 0.5) * 2;
          pointer.ny = (pointer.y - 0.5) * 2;

          if (studioState.prefs.appearance.cardSpotlight) {
            const card = event.target?.closest?.(".summary-card, .template-summary-card, .module-card, .kpi-tile, .quick-entry-tile");
            if (card) {
              const rect = card.getBoundingClientRect();
              card.style.setProperty("--mx", `${(event.clientX - rect.left).toFixed(1)}px`);
              card.style.setProperty("--my", `${(event.clientY - rect.top).toFixed(1)}px`);
            }
          }
        },
        { passive: true },
      );

      syncMode();
    }

    return { init, syncMode };
  })();

  /* ========================================================================
     3. Appearance & Background Studio Modal
     ======================================================================== */

  function openAppearanceModal() {
    const modal = document.getElementById("appearanceModal");
    if (!modal) return;
    closeCardModal(false);
    syncAppearanceModalControls();
    modal.classList.remove("hidden");
    document.body.classList.add("modal-open-body");
  }

  function closeAppearanceModal() {
    const modal = document.getElementById("appearanceModal");
    if (!modal || modal.classList.contains("hidden")) return false;
    modal.classList.add("hidden");
    if (!studioState.activeModal) document.body.classList.remove("modal-open-body");
    return true;
  }

  function renderWallpaperPresetGrid() {
    const host = document.getElementById("wallpaperPresetGrid");
    if (!host) return;
    const app = studioState.prefs.appearance;
    host.innerHTML = WALLPAPER_PRESETS.map((preset) => {
      const active =
        (preset.id === "none" && app.wallpaperType === "none") ||
        (preset.id !== "none" && app.wallpaperType === "preset" && app.wallpaperPreset === preset.id);
      return `
        <button type="button" class="wallpaper-preset-card ${active ? "active" : ""}" data-select-preset="${preset.id}">
          <span class="wallpaper-thumb" style="background:${preset.thumb}"></span>
          <span class="wallpaper-preset-meta">
            <strong>${escapeHtml(preset.name)}</strong>
            <small>${escapeHtml(preset.desc)}</small>
          </span>
        </button>
      `;
    }).join("");
  }

  function renderUploadedWallpapers() {
    const section = document.getElementById("uploadedWallpapersSection");
    const grid = document.getElementById("uploadedWallpapersGrid");
    if (!section || !grid) return;
    const list = studioState.prefs.wallpapers || [];
    if (!list.length) {
      section.classList.add("hidden");
      grid.innerHTML = "";
      return;
    }
    section.classList.remove("hidden");
    const app = studioState.prefs.appearance;
    grid.innerHTML = list
      .map((wp) => {
        const active = app.wallpaperType === "upload" && app.wallpaperUrl === wp.url;
        return `
          <div class="uploaded-wp-card ${active ? "active" : ""}" data-select-upload-wp="${escapeAttr(wp.url)}">
            <img class="uploaded-wp-img" src="${escapeAttr(wp.url)}" alt="" loading="lazy" />
            <div class="uploaded-wp-foot">
              <span class="uploaded-wp-name" title="${escapeAttr(wp.name)}">${escapeHtml(wp.name)}</span>
              <button type="button" class="danger uploaded-wp-del" data-delete-wp="${escapeAttr(wp.name)}">删</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderCustomSkinsGrid() {
    const grid = document.getElementById("customSkinsGrid");
    if (!grid) return;
    const skins = studioState.prefs.skins || [];
    const active = activeCustomSkin();
    if (!skins.length) {
      grid.innerHTML = '<div class="empty-state">尚未导入 .mvskin 皮肤包。点击右上角「导入 .mvskin 皮肤」即可一键加载 Muvyo 皮肤的背景图与配色。</div>';
      return;
    }
    grid.innerHTML = skins
      .map((skin) => {
        const isCurrent = Boolean(active && active.id === skin.id);
        const swatches = (skin.candidates || [])
          .slice(0, 8)
          .map(
            (color, idx) =>
              `<button type="button" class="skin-color-dot ${idx === skin.accent_index ? "selected" : ""}" style="--dot:${escapeAttr(color)}" data-skin-color="${escapeAttr(skin.id)}:${idx}" title="切换该皮肤主色为 ${escapeAttr(color)}" aria-label="色板 ${idx + 1}"></button>`,
          )
          .join("");
        return `
          <article class="custom-skin-card ${isCurrent ? "active" : ""}" data-select-skin="${escapeAttr(skin.id)}">
            <div class="custom-skin-head">
              <img class="skin-avatar-thumb" src="${escapeAttr(skin.avatar_url)}" alt="${escapeAttr(skin.name)}" loading="lazy" />
              <div class="custom-skin-meta">
                <div class="custom-skin-title-row">
                  <strong>${escapeHtml(skin.name)}</strong>
                  ${isCurrent ? '<span class="custom-skin-active-tag">当前启用</span>' : ""}
                </div>
                <small>${escapeHtml(skin.description || "Muvyo .mvskin 自定义皮肤")}</small>
              </div>
            </div>
            <div class="skin-swatch-row">
              <span class="skin-swatch-label">皮肤色板</span>
              ${swatches}
            </div>
            <div class="custom-skin-actions">
              <button type="button" class="${isCurrent ? "primary" : ""}" data-apply-skin="${escapeAttr(skin.id)}">${isCurrent ? "已启用" : "应用皮肤"}</button>
              <a class="skin-action-link" href="${escapeAttr(skin.export_url)}" download="${escapeAttr(skin.name)}.mvskin">导出</a>
              <button type="button" class="danger" data-delete-skin="${escapeAttr(skin.id)}">删除</button>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function syncAppearanceModalControls() {
    const { theme, density, appearance } = studioState.prefs;
    const skin = activeCustomSkin();
    const banner = document.getElementById("appearancePreviewBanner");
    const eyebrow = document.getElementById("appearanceBannerEyebrow");
    const title = document.getElementById("appearanceBannerTitle");
    const desc = document.getElementById("appearanceBannerDesc");
    if (banner) {
      if (skin) {
        banner.style.backgroundImage = `url("${skin.background_url.replace(/"/g, '\\"')}")`;
        const cx = Math.round((skin.avatar?.cx ?? 0.5) * 100);
        const cy = Math.round((skin.avatar?.cy ?? 0.3) * 100);
        banner.style.backgroundPosition = `${cx}% ${cy}%`;
      } else if ((appearance.wallpaperType === "upload" || appearance.wallpaperType === "url") && appearance.wallpaperUrl) {
        banner.style.backgroundImage = `url("${appearance.wallpaperUrl.replace(/"/g, '\\"')}")`;
        banner.style.backgroundPosition = "center";
      } else {
        const preset = WALLPAPER_PRESETS.find((p) => p.id === (appearance.wallpaperType === "none" ? "none" : appearance.wallpaperPreset)) || WALLPAPER_PRESETS[0];
        banner.style.backgroundImage = preset.thumb;
        banner.style.backgroundPosition = "center";
      }
    }
    if (eyebrow) eyebrow.textContent = skin ? "CUSTOM SKIN · MVSKIN" : "LIVE GLASS PREVIEW";
    if (title) title.textContent = currentWallpaperLabel();
    if (desc) {
      if (skin && skin.description) {
        desc.textContent = `${skin.description} · 玻璃 ${appearance.glassOpacity}% · 模糊 ${appearance.glassBlur}px`;
      } else {
        const parts = [
          `玻璃浓度 ${appearance.glassOpacity}%`,
          `模糊 ${appearance.glassBlur}px`,
          ambientEffectLabel(appearance.ambientEffect),
          appearance.mouseParallax ? "鼠标微视差" : "固定背景",
        ];
        desc.textContent = parts.join(" · ");
      }
    }

    document.querySelectorAll("#appearanceThemeSwitch [data-app-theme]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.appTheme === theme);
    });
    document.querySelectorAll("#appearanceDensitySwitch [data-density-option]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.densityOption === density);
    });
    document.querySelectorAll("#appearanceAccentSwatches [data-app-accent]").forEach((btn) => {
      btn.classList.toggle("active", !skin && btn.dataset.appAccent === appearance.accent);
    });
    document.querySelectorAll("#ambientEffectPicker [data-ambient-effect]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.ambientEffect === appearance.ambientEffect);
    });

    const wpRange = document.getElementById("rangeWallpaperOpacity");
    const glRange = document.getElementById("rangeGlassOpacity");
    const blRange = document.getElementById("rangeGlassBlur");
    if (wpRange) wpRange.value = String(appearance.wallpaperOpacity ?? 68);
    if (glRange) glRange.value = String(appearance.glassOpacity ?? 56);
    if (blRange) blRange.value = String(appearance.glassBlur ?? 18);
    const valWp = document.getElementById("valWallpaperOpacity");
    const valGl = document.getElementById("valGlassOpacity");
    const valBl = document.getElementById("valGlassBlur");
    if (valWp) valWp.textContent = `${appearance.wallpaperOpacity ?? 68}%`;
    if (valGl) valGl.textContent = `${appearance.glassOpacity ?? 56}%`;
    if (valBl) valBl.textContent = `${appearance.glassBlur ?? 18}px`;

    const urlInput = document.getElementById("wallpaperUrlInput");
    if (urlInput && document.activeElement !== urlInput) {
      urlInput.value = appearance.wallpaperType === "url" ? appearance.wallpaperUrl || "" : "";
    }

    const parallaxToggle = document.getElementById("toggleMouseParallax");
    const spotToggle = document.getElementById("toggleCardSpotlight");
    const avatarToggle = document.getElementById("toggleShowSkinAvatar");
    if (parallaxToggle) parallaxToggle.checked = Boolean(appearance.mouseParallax);
    if (spotToggle) spotToggle.checked = Boolean(appearance.cardSpotlight);
    if (avatarToggle) avatarToggle.checked = appearance.showSkinAvatar !== false;

    renderCustomSkinsGrid();
    renderWallpaperPresetGrid();
    renderUploadedWallpapers();
  }

  function bindAppearanceModalEvents() {
    document.getElementById("topbarSkinAvatarBtn")?.addEventListener("click", openAppearanceModal);
    document.querySelectorAll("[data-open-appearance]").forEach((el) => {
      el.addEventListener("click", openAppearanceModal);
      if (el.getAttribute("role") === "button") {
        el.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openAppearanceModal();
          }
        });
      }
    });
    document.querySelectorAll("[data-close-appearance]").forEach((el) => {
      el.addEventListener("click", closeAppearanceModal);
    });

    document.getElementById("mvskinFileInput")?.addEventListener("change", async (event) => {
      const input = event.currentTarget;
      const file = input.files?.[0];
      input.value = "";
      if (!file) return;
      if (file.size > 16 * 1024 * 1024) {
        showToast("皮肤包不能超过 16 MB", "error");
        return;
      }
      try {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(new Error("读取皮肤文件失败"));
          reader.readAsDataURL(file);
        });
        showToast("正在解析并导入 .mvskin 皮肤...", "success");
        const res = await postJson("/api/ui/skins/import", { filename: file.name, data_b64: dataUrl });
        if (!res?.ok || !res?.skin?.id) throw new Error(res?.error || "导入失败");
        studioState.prefs.skins = res.skins || [];
        studioState.prefs.appearance.wallpaperType = "skin";
        studioState.prefs.appearance.skinId = res.skin.id;
        applyAllPreferences(true);
        showToast(`已导入并启用皮肤「${res.skin.name}」`, "success");
      } catch (err) {
        showToast(`导入失败：${err.message}`, "error");
      }
    });

    document.getElementById("customSkinsGrid")?.addEventListener("click", async (event) => {
      if (event.target.closest("a.skin-action-link")) return;

      const dot = event.target.closest("[data-skin-color]");
      if (dot) {
        event.stopPropagation();
        const [skinId, idxStr] = dot.dataset.skinColor.split(":");
        const idx = Number(idxStr);
        try {
          const res = await postJson("/api/ui/skins/update", { id: skinId, accent_index: idx });
          if (res?.skins) studioState.prefs.skins = res.skins;
          studioState.prefs.appearance.wallpaperType = "skin";
          studioState.prefs.appearance.skinId = skinId;
          applyAllPreferences(true);
        } catch (err) {
          showToast(`切换皮肤主色失败：${err.message}`, "error");
        }
        return;
      }

      const delBtn = event.target.closest("[data-delete-skin]");
      if (delBtn) {
        event.stopPropagation();
        const skinId = delBtn.dataset.deleteSkin;
        if (!window.confirm("确认删除此自定义皮肤？")) return;
        try {
          const res = await postJson("/api/ui/skins/delete", { id: skinId });
          studioState.prefs.skins = res.skins || [];
          if (studioState.prefs.appearance.skinId === skinId) {
            studioState.prefs.appearance.wallpaperType = "preset";
            studioState.prefs.appearance.skinId = "";
          }
          applyAllPreferences(true);
          showToast("已删除自定义皮肤", "success");
        } catch (err) {
          showToast(`删除失败：${err.message}`, "error");
        }
        return;
      }

      const applyEl = event.target.closest("[data-apply-skin], [data-select-skin]");
      if (!applyEl) return;
      const skinId = applyEl.dataset.applySkin || applyEl.dataset.selectSkin;
      studioState.prefs.appearance.wallpaperType = "skin";
      studioState.prefs.appearance.skinId = skinId;
      applyAllPreferences(true);
      const skin = activeCustomSkin();
      if (skin) showToast(`已切换到皮肤「${skin.name}」`, "success");
    });

    document.getElementById("appearanceThemeSwitch")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-app-theme]");
      if (!btn) return;
      studioState.prefs.theme = btn.dataset.appTheme;
      applyAllPreferences(true);
    });

    document.getElementById("appearanceAccentSwatches")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-app-accent]");
      if (!btn) return;
      studioState.prefs.appearance.accent = btn.dataset.appAccent;
      if (studioState.prefs.appearance.wallpaperType === "skin") {
        studioState.prefs.appearance.wallpaperType = "preset";
        studioState.prefs.appearance.skinId = "";
      }
      applyAllPreferences(true);
    });

    document.getElementById("wallpaperPresetGrid")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-select-preset]");
      if (!btn) return;
      const presetId = btn.dataset.selectPreset;
      if (presetId === "none") {
        studioState.prefs.appearance.wallpaperType = "none";
      } else {
        studioState.prefs.appearance.wallpaperType = "preset";
        studioState.prefs.appearance.wallpaperPreset = presetId;
      }
      applyAllPreferences(true);
    });

    document.getElementById("wallpaperFileInput")?.addEventListener("change", async (event) => {
      const input = event.currentTarget;
      const file = input.files?.[0];
      input.value = "";
      if (!file) return;
      if (file.size > 8 * 1024 * 1024) {
        showToast("背景图不能超过 8 MB", "error");
        return;
      }
      try {
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(new Error("读取图片失败"));
          reader.readAsDataURL(file);
        });
        showToast("正在上传背景图...", "success");
        const res = await postJson("/api/ui/wallpaper", { filename: file.name, data_url: dataUrl });
        if (!res?.ok || !res?.wallpaper?.url) throw new Error(res?.error || "上传失败");
        studioState.prefs.wallpapers = res.wallpapers || [];
        studioState.prefs.appearance.wallpaperType = "upload";
        studioState.prefs.appearance.wallpaperUrl = res.wallpaper.url;
        applyAllPreferences(true);
        showToast("背景图已上传并应用", "success");
      } catch (err) {
        showToast(`上传失败：${err.message}`, "error");
      }
    });

    document.getElementById("applyWallpaperUrlBtn")?.addEventListener("click", () => {
      const raw = (document.getElementById("wallpaperUrlInput")?.value || "").trim();
      if (!raw) {
        showToast("请输入有效的图片地址（http:// 或 https://）", "error");
        return;
      }
      if (!/^https?:\/\//i.test(raw) && !raw.startsWith("/api/ui/wallpapers/")) {
        showToast("仅支持 http(s):// 图片链接", "error");
        return;
      }
      studioState.prefs.appearance.wallpaperType = "url";
      studioState.prefs.appearance.wallpaperUrl = raw;
      applyAllPreferences(true);
      showToast("已应用在线背景图", "success");
    });

    document.getElementById("uploadedWallpapersGrid")?.addEventListener("click", async (event) => {
      const delBtn = event.target.closest("[data-delete-wp]");
      if (delBtn) {
        event.stopPropagation();
        const name = delBtn.dataset.deleteWp;
        try {
          const res = await postJson("/api/ui/wallpaper/delete", { name });
          studioState.prefs.wallpapers = res.wallpapers || [];
          if (studioState.prefs.appearance.wallpaperUrl === `/api/ui/wallpapers/${name}`) {
            studioState.prefs.appearance.wallpaperType = "preset";
            studioState.prefs.appearance.wallpaperUrl = "";
          }
          applyAllPreferences(true);
          showToast("已删除壁纸", "success");
        } catch (err) {
          showToast(`删除失败：${err.message}`, "error");
        }
        return;
      }
      const card = event.target.closest("[data-select-upload-wp]");
      if (!card) return;
      studioState.prefs.appearance.wallpaperType = "upload";
      studioState.prefs.appearance.wallpaperUrl = card.dataset.selectUploadWp;
      applyAllPreferences(true);
    });

    const bindSlider = (id, key) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", () => {
        studioState.prefs.appearance[key] = Number(el.value);
        applyAllPreferences(true);
      });
    };
    bindSlider("rangeWallpaperOpacity", "wallpaperOpacity");
    bindSlider("rangeGlassOpacity", "glassOpacity");
    bindSlider("rangeGlassBlur", "glassBlur");

    document.getElementById("ambientEffectPicker")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-ambient-effect]");
      if (!btn) return;
      studioState.prefs.appearance.ambientEffect = btn.dataset.ambientEffect;
      applyAllPreferences(true);
    });

    document.getElementById("toggleMouseParallax")?.addEventListener("change", (event) => {
      studioState.prefs.appearance.mouseParallax = event.currentTarget.checked;
      applyAllPreferences(true);
    });
    document.getElementById("toggleCardSpotlight")?.addEventListener("change", (event) => {
      studioState.prefs.appearance.cardSpotlight = event.currentTarget.checked;
      applyAllPreferences(true);
    });
    document.getElementById("toggleShowSkinAvatar")?.addEventListener("change", (event) => {
      studioState.prefs.appearance.showSkinAvatar = event.currentTarget.checked;
      applyAllPreferences(true);
    });

    document.getElementById("resetAppearanceBtn")?.addEventListener("click", () => {
      studioState.prefs.appearance = defaultAppearance();
      studioState.prefs.theme = "dark";
      studioState.prefs.density = "comfortable";
      applyAllPreferences(true);
      showToast("已恢复默认外观设置", "success");
    });
  }

  /* ========================================================================
     4. Dynamic Sidebar Rendering & Muvyo-Style Sidebar Arrange Studio
     ======================================================================== */

  function renderSidebarFromLayout() {
    const nav = document.getElementById("sideNav");
    if (!nav) return;
    const layout = studioState.prefs.sidebarLayout || defaultSidebarLayout();
    const enabledById = new Map((state.modules || []).map((m) => [m.id, Boolean(m.enabled)]));
    const activeView = state.currentView || "dashboard";

    nav.innerHTML = layout
      .filter((group) => Array.isArray(group.items) && group.items.length > 0)
      .map((group) => {
        const hasTitle = Boolean(String(group.title || "").trim());
        const itemsHtml = group.items
          .map((viewId) => {
            const meta = FEATURE_BY_ID.get(viewId);
            if (!meta) return "";
            const isEnabled = meta.moduleId ? enabledById.get(meta.moduleId) : false;
            const modAttr = meta.moduleId ? ` data-module-nav="${escapeAttr(meta.moduleId)}"` : "";
            const dotHtml = meta.moduleId ? '<span class="nav-dot" aria-hidden="true"></span>' : "";
            return `
              <button class="nav-item ${activeView === viewId ? "active" : ""} ${isEnabled ? "is-enabled" : ""}" data-view="${escapeAttr(viewId)}"${modAttr} data-tooltip="${escapeAttr(meta.label)}" title="${escapeAttr(meta.label)}">
                <span class="nav-ico">${iconSvg(meta.icon)}</span>
                <span class="nav-label">${escapeHtml(meta.label)}</span>
                ${dotHtml}
              </button>
            `;
          })
          .join("");
        return `
          <div class="nav-section ${hasTitle ? "" : "no-title"}" data-nav-group="${escapeAttr(group.id)}">
            ${hasTitle ? `<div class="nav-section-title">${escapeHtml(group.title)}</div>` : ""}
            ${itemsHtml}
          </div>
        `;
      })
      .join("");
  }

  function layoutAssignedSet() {
    const set = new Set();
    (studioState.prefs.sidebarLayout || []).forEach((g) => {
      (g.items || []).forEach((id) => set.add(id));
    });
    return set;
  }

  function mutateLayout(mutator) {
    const next = cloneJson(studioState.prefs.sidebarLayout || defaultSidebarLayout());
    mutator(next);
    studioState.prefs.sidebarLayout = next;
    renderSidebarFromLayout();
    renderArrangeStudio();
    updateSettingsStudioBadges();
    schedulePrefsSave({ immediate: true, includeSidebar: true });
  }

  function renderArrangeStudio() {
    const groupsHost = document.getElementById("arrangeGroupsHost");
    const poolHost = document.getElementById("arrangePoolHost");
    if (!groupsHost || !poolHost) return;

    const layout = studioState.prefs.sidebarLayout || defaultSidebarLayout();
    const assigned = layoutAssignedSet();
    const q = (studioState.arrangeSearch || "").trim().toLowerCase();

    const totalItems = assigned.size;
    const metaEl = document.getElementById("arrangeStructureMeta");
    if (metaEl) metaEl.textContent = `${layout.length} 组 · ${totalItems} 项 · 分组名 = 分隔符`;
    const poolMeta = document.getElementById("arrangePoolMeta");
    if (poolMeta) poolMeta.textContent = `${Math.max(FEATURE_CATALOG.length - totalItems, 0)} 待选 / ${FEATURE_CATALOG.length}`;

    // Left Column: Groups & Items
    groupsHost.innerHTML = layout
      .map((group, gIdx) => {
        const itemsHtml = group.items
          .map((viewId, iIdx) => {
            const meta = FEATURE_BY_ID.get(viewId);
            if (!meta) return "";
            if (q && !meta.label.toLowerCase().includes(q) && !meta.category.toLowerCase().includes(q) && !group.title.toLowerCase().includes(q)) {
              return "";
            }
            const menuKey = `${gIdx}:${viewId}`;
            const menuOpen = studioState.openMoveMenuKey === menuKey;
            const otherGroupsHtml = layout
              .map((targetG, tIdx) =>
                tIdx === gIdx
                  ? ""
                  : `<button type="button" data-move-item="${gIdx}:${iIdx}:${tIdx}">移到「${escapeHtml(targetG.title || `第 ${tIdx + 1} 组`)}」</button>`,
              )
              .join("");
            return `
              <div class="arrange-item-row" draggable="true" data-drag-kind="sidebar-item" data-group-idx="${gIdx}" data-item-idx="${iIdx}" data-view-id="${escapeAttr(viewId)}">
                <span class="drag-handle" title="拖动排序">⋮⋮</span>
                <span class="arrange-row-name">
                  <span class="nav-ico mini-ico">${iconSvg(meta.icon)}</span>
                  <span>${escapeHtml(meta.label)}</span>
                </span>
                <button type="button" class="arrange-mini-btn" data-item-up="${gIdx}:${iIdx}" ${iIdx === 0 ? "disabled" : ""} title="上移">↑</button>
                <button type="button" class="arrange-mini-btn" data-item-down="${gIdx}:${iIdx}" ${iIdx === group.items.length - 1 ? "disabled" : ""} title="下移">↓</button>
                <button type="button" class="arrange-mini-btn" data-toggle-move-menu="${escapeAttr(menuKey)}" title="移到其它分组或移出">⋯</button>
                ${
                  menuOpen
                    ? `<div class="arrange-move-menu">
                        ${otherGroupsHtml}
                        <button type="button" class="danger-item" data-remove-item="${gIdx}:${iIdx}">从侧边栏移出</button>
                      </div>`
                    : ""
                }
              </div>
            `;
          })
          .join("");

        return `
          <div class="arrange-group-card" data-drop-group="${gIdx}">
            <div class="arrange-group-head">
              <input type="text" class="arrange-group-input" data-group-title="${gIdx}" value="${escapeAttr(group.title)}" placeholder="留空 = 不显示分隔符" aria-label="分组名" />
              <span class="arrange-count-badge">${group.items.length}</span>
              <button type="button" class="arrange-mini-btn" data-group-up="${gIdx}" ${gIdx === 0 ? "disabled" : ""} title="分组上移">↑</button>
              <button type="button" class="arrange-mini-btn" data-group-down="${gIdx}" ${gIdx === layout.length - 1 ? "disabled" : ""} title="分组下移">↓</button>
              <button type="button" class="arrange-mini-btn" data-group-delete="${gIdx}" title="删除分组">✕</button>
            </div>
            <div class="arrange-items-list">
              ${itemsHtml || '<p class="arrange-empty-drop">从右侧拖入或点击 + 添加功能</p>'}
            </div>
          </div>
        `;
      })
      .join("");

    // Right Column: Full Feature Pool by Category
    const categories = [];
    const byCat = new Map();
    FEATURE_CATALOG.forEach((item) => {
      if (q && !item.label.toLowerCase().includes(q) && !item.category.toLowerCase().includes(q) && !item.id.toLowerCase().includes(q)) {
        return;
      }
      if (!byCat.has(item.category)) {
        byCat.set(item.category, []);
        categories.push(item.category);
      }
      byCat.get(item.category).push(item);
    });

    poolHost.innerHTML =
      categories
        .map((cat) => {
          const rows = byCat
            .get(cat)
            .map((item) => {
              const inSidebar = assigned.has(item.id);
              return `
                <div class="arrange-pool-row" draggable="true" data-drag-kind="pool-item" data-view-id="${escapeAttr(item.id)}">
                  <span class="drag-handle" title="拖到左侧加入">⋮⋮</span>
                  <button type="button" class="arrange-pool-name-btn" data-pool-open="${escapeAttr(item.id)}">
                    <span class="nav-ico mini-ico">${iconSvg(item.icon)}</span>
                    <span>${escapeHtml(item.label)}</span>
                  </button>
                  ${
                    inSidebar
                      ? `<span class="arrange-in-pill">已在侧边栏</span>
                         <button type="button" class="arrange-mini-btn" data-pool-remove="${escapeAttr(item.id)}" title="移出侧边栏">−</button>`
                      : `<button type="button" class="arrange-mini-btn accent-plus" data-pool-add="${escapeAttr(item.id)}" title="加入侧边栏">+</button>`
                  }
                </div>
              `;
            })
            .join("");
          return `
            <div class="arrange-pool-cat">
              <div class="arrange-pool-cat-label">${escapeHtml(cat)}</div>
              ${rows}
            </div>
          `;
        })
        .join("") || '<div class="empty-state">没有匹配的功能项</div>';
  }

  function bindArrangeStudioEvents() {
    document.getElementById("sideNav")?.addEventListener("click", (event) => {
      const btn = event.target.closest(".nav-item[data-view]");
      if (!btn) return;
      showView(btn.dataset.view);
    });

    document.getElementById("arrangeSearchInput")?.addEventListener("input", (event) => {
      studioState.arrangeSearch = event.currentTarget.value || "";
      renderArrangeStudio();
    });

    document.getElementById("arrangeApplyRecommended")?.addEventListener("click", () => {
      studioState.openMoveMenuKey = null;
      studioState.prefs.sidebarLayout = recommendedSidebarLayout();
      renderSidebarFromLayout();
      renderArrangeStudio();
      updateSettingsStudioBadges();
      schedulePrefsSave({ immediate: true, includeSidebar: true });
      showToast("已应用精简推荐侧边栏结构并保存", "success");
    });

    document.getElementById("arrangeResetDefault")?.addEventListener("click", () => {
      studioState.openMoveMenuKey = null;
      studioState.prefs.sidebarLayout = defaultSidebarLayout();
      renderSidebarFromLayout();
      renderArrangeStudio();
      updateSettingsStudioBadges();
      schedulePrefsSave({ immediate: true, includeSidebar: true });
      showToast("已恢复默认完整侧边栏结构并保存", "success");
    });

    document.getElementById("arrangeAddGroup")?.addEventListener("click", () => {
      mutateLayout((layout) => {
        layout.push({ id: `group_${Date.now()}`, title: "新分组", items: [] });
      });
    });

    const groupsHost = document.getElementById("arrangeGroupsHost");
    const poolHost = document.getElementById("arrangePoolHost");

    groupsHost?.addEventListener("input", (event) => {
      const input = event.target.closest("[data-group-title]");
      if (!input) return;
      const idx = Number(input.dataset.groupTitle);
      if (studioState.prefs.sidebarLayout[idx]) {
        studioState.prefs.sidebarLayout[idx].title = input.value;
        renderSidebarFromLayout();
        schedulePrefsSave({ includeSidebar: true });
      }
    });

    document.getElementById("arrangeSaveStatus")?.addEventListener("click", () => {
      if (studioState.pendingSidebarSave) {
        void flushPrefsSave({ includeSidebar: true });
      }
    });

    const flushOnLeave = () => {
      if (studioState.saveTimer || studioState.pendingSidebarSave) {
        void flushPrefsSave({ includeSidebar: studioState.pendingSidebarSave, keepalive: true });
      }
    };
    window.addEventListener("pagehide", flushOnLeave);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flushOnLeave();
    });

    groupsHost?.addEventListener("click", (event) => {
      const t = event.target;
      const gUp = t.closest("[data-group-up]");
      if (gUp) {
        const i = Number(gUp.dataset.groupUp);
        if (i > 0) mutateLayout((l) => ([l[i - 1], l[i]] = [l[i], l[i - 1]]));
        return;
      }
      const gDown = t.closest("[data-group-down]");
      if (gDown) {
        const i = Number(gDown.dataset.groupDown);
        mutateLayout((l) => {
          if (i < l.length - 1) [l[i], l[i + 1]] = [l[i + 1], l[i]];
        });
        return;
      }
      const gDel = t.closest("[data-group-delete]");
      if (gDel) {
        const i = Number(gDel.dataset.groupDelete);
        mutateLayout((l) => {
          if (l.length <= 1) {
            l[0].items = [];
          } else {
            l.splice(i, 1);
          }
        });
        return;
      }
      const iUp = t.closest("[data-item-up]");
      if (iUp) {
        const [gIdx, iIdx] = iUp.dataset.itemUp.split(":").map(Number);
        if (iIdx > 0) mutateLayout((l) => ([l[gIdx].items[iIdx - 1], l[gIdx].items[iIdx]] = [l[gIdx].items[iIdx], l[gIdx].items[iIdx - 1]]));
        return;
      }
      const iDown = t.closest("[data-item-down]");
      if (iDown) {
        const [gIdx, iIdx] = iDown.dataset.itemDown.split(":").map(Number);
        mutateLayout((l) => {
          const arr = l[gIdx].items;
          if (iIdx < arr.length - 1) [arr[iIdx], arr[iIdx + 1]] = [arr[iIdx + 1], arr[iIdx]];
        });
        return;
      }
      const menuBtn = t.closest("[data-toggle-move-menu]");
      if (menuBtn) {
        event.stopPropagation();
        const key = menuBtn.dataset.toggleMoveMenu;
        studioState.openMoveMenuKey = studioState.openMoveMenuKey === key ? null : key;
        renderArrangeStudio();
        return;
      }
      const moveBtn = t.closest("[data-move-item]");
      if (moveBtn) {
        const [fromG, fromI, toG] = moveBtn.dataset.moveItem.split(":").map(Number);
        studioState.openMoveMenuKey = null;
        mutateLayout((l) => {
          const [moved] = l[fromG].items.splice(fromI, 1);
          if (moved) l[toG].items.push(moved);
        });
        return;
      }
      const remBtn = t.closest("[data-remove-item]");
      if (remBtn) {
        const [gIdx, iIdx] = remBtn.dataset.removeItem.split(":").map(Number);
        studioState.openMoveMenuKey = null;
        mutateLayout((l) => l[gIdx].items.splice(iIdx, 1));
      }
    });

    poolHost?.addEventListener("click", (event) => {
      const openBtn = event.target.closest("[data-pool-open]");
      if (openBtn) {
        showView(openBtn.dataset.poolOpen);
        return;
      }
      const addBtn = event.target.closest("[data-pool-add]");
      if (addBtn) {
        const viewId = addBtn.dataset.poolAdd;
        const meta = FEATURE_BY_ID.get(viewId);
        mutateLayout((l) => {
          if (!l.length) l.push({ id: `group_${Date.now()}`, title: meta?.category || "默认分组", items: [] });
          const match = l.find((g) => g.title === meta?.category);
          (match || l[l.length - 1]).items.push(viewId);
        });
        return;
      }
      const remBtn = event.target.closest("[data-pool-remove]");
      if (remBtn) {
        const viewId = remBtn.dataset.poolRemove;
        mutateLayout((l) => {
          l.forEach((g) => {
            g.items = g.items.filter((id) => id !== viewId);
          });
        });
      }
    });

    // HTML5 Drag & Drop across groups and from pool
    const arrangeView = document.getElementById("sidebarArrange");
    arrangeView?.addEventListener("dragstart", (event) => {
      const row = event.target.closest("[data-drag-kind]");
      if (!row) return;
      studioState.dragPayload = {
        kind: row.dataset.dragKind,
        viewId: row.dataset.viewId,
        groupIdx: row.dataset.groupIdx !== undefined ? Number(row.dataset.groupIdx) : -1,
        itemIdx: row.dataset.itemIdx !== undefined ? Number(row.dataset.itemIdx) : -1,
      };
      row.classList.add("dragging");
      event.dataTransfer?.setData("text/plain", row.dataset.viewId || "");
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
    });

    arrangeView?.addEventListener("dragend", () => {
      studioState.dragPayload = null;
      arrangeView.querySelectorAll(".dragging, .drag-over, .drag-over-row").forEach((el) => {
        el.classList.remove("dragging", "drag-over", "drag-over-row");
      });
    });

    groupsHost?.addEventListener("dragover", (event) => {
      if (!studioState.dragPayload) return;
      const groupCard = event.target.closest("[data-drop-group]");
      if (!groupCard) return;
      event.preventDefault();
      groupsHost.querySelectorAll(".drag-over, .drag-over-row").forEach((el) => el.classList.remove("drag-over", "drag-over-row"));
      groupCard.classList.add("drag-over");
      const targetRow = event.target.closest(".arrange-item-row");
      if (targetRow) targetRow.classList.add("drag-over-row");
    });

    groupsHost?.addEventListener("drop", (event) => {
      if (!studioState.dragPayload) return;
      const groupCard = event.target.closest("[data-drop-group]");
      if (!groupCard) return;
      event.preventDefault();
      const targetGroupIdx = Number(groupCard.dataset.dropGroup);
      const targetRow = event.target.closest(".arrange-item-row");
      const targetItemIdx = targetRow ? Number(targetRow.dataset.itemIdx) : -1;
      const payload = studioState.dragPayload;
      studioState.dragPayload = null;

      mutateLayout((l) => {
        if (!l[targetGroupIdx]) return;
        // Remove existing occurrence if any
        l.forEach((g) => {
          g.items = g.items.filter((id) => id !== payload.viewId);
        });
        const dest = l[targetGroupIdx].items;
        if (targetItemIdx >= 0 && targetItemIdx <= dest.length) {
          dest.splice(targetItemIdx, 0, payload.viewId);
        } else {
          dest.push(payload.viewId);
        }
      });
    });

    document.addEventListener("click", (event) => {
      if (studioState.openMoveMenuKey && !event.target.closest(".arrange-move-menu") && !event.target.closest("[data-toggle-move-menu]")) {
        studioState.openMoveMenuKey = null;
        renderArrangeStudio();
      }
    });
  }

  /* ========================================================================
     5. Universal Glass Modal Card Promotion Engine
     ======================================================================== */

  function ensureCardModalChrome(cardEl, meta) {
    if (cardEl.dataset.modalChromeReady === "1") {
      const h3 = cardEl.querySelector(":scope > .modal-card-head h3");
      const p = cardEl.querySelector(":scope > .modal-card-head p");
      const ico = cardEl.querySelector(":scope > .modal-card-head .dialog-ico");
      if (h3 && meta.title) h3.textContent = meta.title;
      if (p) p.textContent = meta.subtitle || "";
      if (ico && meta.icon) ico.innerHTML = iconSvg(meta.icon);
      return;
    }

    const head = document.createElement("div");
    head.className = "modal-card-head";
    head.innerHTML = `
      <div class="modal-card-head-left">
        <span class="dialog-ico">${iconSvg(meta.icon || "settings")}</span>
        <div>
          <h3>${escapeHtml(meta.title || "编辑配置")}</h3>
          <p>${escapeHtml(meta.subtitle || "")}</p>
        </div>
      </div>
      <button type="button" class="icon-btn dialog-close-btn" data-modal-close aria-label="关闭弹窗">✕</button>
    `;

    const body = document.createElement("div");
    body.className = "modal-card-body";
    while (cardEl.firstChild) {
      body.appendChild(cardEl.firstChild);
    }

    const foot = document.createElement("div");
    foot.className = "modal-card-foot";
    foot.innerHTML = `
      <span class="modal-card-foot-hint">编辑完成后点击保存立即生效</span>
      <div class="modal-card-foot-actions">
        <button type="button" class="ghost-btn" data-modal-close>关闭</button>
        ${meta.saveBtnId ? `<button type="button" class="primary" data-modal-save="${escapeAttr(meta.saveBtnId)}">${escapeHtml(meta.saveLabel || "保存配置")}</button>` : ""}
      </div>
    `;

    cardEl.appendChild(head);
    cardEl.appendChild(body);
    cardEl.appendChild(foot);
    cardEl.dataset.modalChromeReady = "1";

    cardEl.querySelectorAll("[data-modal-close]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        closeCardModal(true);
      });
    });

    const saveProxy = cardEl.querySelector("[data-modal-save]");
    if (saveProxy) {
      saveProxy.addEventListener("click", (event) => {
        event.stopPropagation();
        const targetId = saveProxy.dataset.modalSave;
        const realBtn = document.getElementById(targetId);
        if (realBtn) realBtn.click();
      });
    }

    cardEl.addEventListener("click", (event) => {
      if (!event.target.closest('[data-action^="remove-"]')) return;
      window.setTimeout(() => {
        if (studioState.activeModal?.cardEl === cardEl && !document.body.contains(cardEl)) {
          closeCardModal(true);
        }
      }, 0);
    });
  }

  function openCardModal(cardEl, meta = {}) {
    if (!cardEl) return;
    closeAppearanceModal();
    if (studioState.activeModal) closeCardModal(false);

    const view = cardEl.closest(".view");
    const viewId = view?.id || state.currentView;
    const saveBtnId = meta.saveBtnId ?? (viewId === "moduleRedPacket" ? "saveRedPacketTemplates" : view?.dataset?.saveBtn || "");
    const title = meta.title || cardEl.dataset.modalTitle || cardEl.querySelector("h2, h3")?.textContent?.trim() || "编辑配置";
    const subtitle = meta.subtitle || cardEl.dataset.modalSubtitle || cardEl.querySelector(".section-head .hint, .panel-caption, .provider-head .hint")?.textContent?.trim() || "";
    const icon = meta.icon || cardEl.dataset.modalIcon || viewIconMap[viewId] || "settings";

    ensureCardModalChrome(cardEl, { title, subtitle, icon, saveBtnId, saveLabel: meta.saveLabel || "保存配置" });

    // Walk ancestors so fixed modal is guaranteed viewport-centered and never trapped inside sticky stacking contexts
    const ancestors = [];
    const stickyAncestors = [];
    let cur = cardEl.parentElement;
    while (cur && cur !== document.body) {
      if (window.getComputedStyle(cur).position === "sticky") {
        cur.classList.add("modal-sticky-passthrough");
        stickyAncestors.push(cur);
      }
      cur.classList.add("modal-ancestor-passthrough");
      ancestors.push(cur);
      cur = cur.parentElement;
    }
    const tabPane = cardEl.closest(".tab-pane");
    if (tabPane) tabPane.classList.add("has-open-modal");

    cardEl.classList.add("is-modal-open");
    document.getElementById("glassModalBackdrop")?.classList.remove("hidden");
    document.body.classList.add("modal-open-body");

    studioState.activeModal = { cardEl, viewId, ancestors, stickyAncestors, tabPane, saveBtnId };

    // Focus first editable input softly
    window.requestAnimationFrame(() => {
      const firstInput = cardEl.querySelector("input:not([type='hidden']):not([disabled]), textarea:not([disabled]), select:not([disabled])");
      if (firstInput && typeof firstInput.focus === "function") firstInput.focus({ preventScroll: true });
    });
  }

  function closeCardModal(refreshSummary = true) {
    const active = studioState.activeModal;
    if (!active) return false;
    active.cardEl.classList.remove("is-modal-open");
    active.ancestors.forEach((el) => el.classList.remove("modal-ancestor-passthrough"));
    (active.stickyAncestors || []).forEach((el) => el.classList.remove("modal-sticky-passthrough"));
    if (active.tabPane) active.tabPane.classList.remove("has-open-modal");
    document.getElementById("glassModalBackdrop")?.classList.add("hidden");
    document.body.classList.remove("modal-open-body");
    const closedViewId = active.viewId;
    studioState.activeModal = null;
    if (refreshSummary && closedViewId) {
      renderSummaryHubForView(closedViewId);
    }
    return true;
  }

  /* ========================================================================
     6. Full-App Muvyo-Style Summary Hub Generators (All 16 Modules + AI + Settings)
     ======================================================================== */

  function formVal(formId, name) {
    const form = document.getElementById(formId);
    const el = form?.elements?.[name];
    if (!el) return "";
    if (el.type === "checkbox") return el.checked;
    return String(el.value || "").trim();
  }

  function countLines(text) {
    return String(text || "")
      .split(/\n/)
      .map((s) => s.trim())
      .filter(Boolean).length;
  }

  function firstLines(text, max = 3) {
    return String(text || "")
      .split(/\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, max);
  }

  function clipText(text, max = 46) {
    const s = String(text || "").replace(/\s+/g, " ").trim();
    return s.length > max ? `${s.slice(0, max)}…` : s;
  }

  function makeSummaryCardHtml({ icon, title, desc, pillText = "", pillKind = "", chips = [], sectionIdx, sectionId, actionButtonsHtml = "" }) {
    const targetAttr = sectionId ? `data-open-section="${escapeAttr(sectionId)}"` : `data-open-section-idx="${sectionIdx}"`;
    const chipsHtml = chips.filter(Boolean).map((c) => `<span class="summary-chip">${escapeHtml(c)}</span>`).join("");
    return `
      <article class="summary-card" ${targetAttr} tabindex="0" role="button">
        <div class="summary-card-top">
          <div class="summary-card-title-row">
            <span class="summary-card-ico">${iconSvg(icon || "settings")}</span>
            <h3>${escapeHtml(title)}</h3>
          </div>
          <div class="summary-card-right">
            ${pillText ? `<span class="summary-pill ${pillKind}">${escapeHtml(pillText)}</span>` : ""}
            <span class="summary-card-more" title="点击编辑" aria-hidden="true">⋯</span>
          </div>
        </div>
        ${desc ? `<p class="summary-card-desc">${escapeHtml(desc)}</p>` : ""}
        ${chipsHtml ? `<div class="summary-card-chips">${chipsHtml}</div>` : ""}
        ${actionButtonsHtml ? `<div class="summary-card-inline-actions">${actionButtonsHtml}</div>` : ""}
      </article>
    `;
  }

  function ensureSummaryHost(viewEl, insertBeforeEl, idSuffix) {
    const id = `summaryHub_${idSuffix}`;
    let host = document.getElementById(id);
    if (!host) {
      host = document.createElement("div");
      host.id = id;
      host.className = "summary-hub";
      if (insertBeforeEl && insertBeforeEl.parentElement) {
        insertBeforeEl.parentElement.insertBefore(host, insertBeforeEl);
      } else {
        viewEl.appendChild(host);
      }
    }
    return host;
  }

  function renderTemplateSummaryGrid(viewId, listSelector, extractor, emptyText) {
    const listEl = document.querySelector(listSelector);
    if (!listEl) return "";
    listEl.classList.add("modal-template-source");
    const cards = Array.from(listEl.querySelectorAll(":scope > .template-card"));
    if (!cards.length) {
      return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    }
    return `
      <div class="template-summary-grid">
        ${cards
          .map((card, idx) => {
            const info = extractor(card, idx);
            const chipsHtml = (info.chips || []).filter(Boolean).map((c) => `<span class="summary-chip">${escapeHtml(c)}</span>`).join("");
            return `
              <article class="template-summary-card ${info.enabled ? "" : "is-disabled"}" data-open-template="${escapeAttr(listSelector)}" data-template-idx="${idx}" tabindex="0" role="button">
                <div class="summary-card-top">
                  <div class="summary-card-title-row">
                    <span class="summary-card-ico">${iconSvg(info.icon || "modules")}</span>
                    <h4>${escapeHtml(info.title)}</h4>
                  </div>
                  <div class="template-summary-actions">
                    ${info.pillText ? `<span class="summary-pill ${info.pillKind || ""}">${escapeHtml(info.pillText)}</span>` : ""}
                    <label class="switch module-inline-switch" title="启用或禁用此项" data-stop-card>
                      <input type="checkbox" ${info.enabled ? "checked" : ""} data-proxy-tpl-toggle="${escapeAttr(listSelector)}" data-template-idx="${idx}" />
                      <span></span>
                    </label>
                    <button type="button" class="danger mini-icon-action" data-proxy-tpl-remove="${escapeAttr(listSelector)}" data-template-idx="${idx}" title="删除此项">删</button>
                  </div>
                </div>
                ${info.desc ? `<p class="summary-card-desc">${escapeHtml(info.desc)}</p>` : ""}
                ${chipsHtml ? `<div class="summary-card-chips">${chipsHtml}</div>` : ""}
              </article>
            `;
          })
          .join("")}
      </div>
    `;
  }

  function renderSummaryHubForView(viewId) {
    const viewEl = document.getElementById(viewId);
    if (!viewEl) return;

    if (viewId === "settings") {
      updateSettingsStudioBadges();
      return;
    }

    if (viewId === "aiServices") {
      const layout = viewEl.querySelector(".ai-service-layout");
      if (!layout) return;
      const cards = Array.from(layout.querySelectorAll(":scope > .section-card"));
      cards.forEach((c) => c.classList.add("modal-card-source"));
      const host = ensureSummaryHost(viewEl, layout, "aiServices");

      const replyForm = document.querySelector('.service-form[data-provider="reply_provider"]');
      const imageForm = document.querySelector('.service-form[data-provider="image_provider"]');
      const replyHasKey = document.getElementById("replyKeyState")?.classList.contains("configured");
      const imageHasKey = document.getElementById("imageKeyState")?.classList.contains("configured");
      const replyType = replyForm?.elements?.provider_type?.selectedOptions?.[0]?.textContent || "OpenAI";
      const imageType = imageForm?.elements?.provider_type?.selectedOptions?.[0]?.textContent || "OpenAI";

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>模型供应商连接</span><small class="hint">点击卡片在弹窗中编辑 URL、API Key 与模型</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "ai_reply",
              title: "回复与视觉服务",
              desc: "供 AI 自动回复、群友画像与 AI 解密共用。",
              pillText: replyHasKey ? "已配置 Key" : "未配置 Key",
              pillKind: replyHasKey ? "ok" : "warn",
              chips: [
                replyForm?.elements?.model?.value ? `模型: ${replyForm.elements.model.value}` : "未填模型",
                replyType,
                replyForm?.elements?.base_url?.value ? clipText(replyForm.elements.base_url.value, 38) : "",
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "ai_image",
              title: "生图专用服务",
              desc: "供 AI 生图模块使用；API Key 留空时默认沿用回复服务 Key。",
              pillText: imageHasKey ? "已配置独立 Key" : "沿用回复 Key",
              pillKind: imageHasKey ? "ok" : "accent",
              chips: [
                imageForm?.elements?.model?.value ? `模型: ${imageForm.elements.model.value}` : "未填模型",
                imageType,
                imageForm?.elements?.base_url?.value ? clipText(imageForm.elements.base_url.value, 38) : "",
              ],
              sectionIdx: 1,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, cards, viewId);
      return;
    }

    if (viewId === "moduleRedPacket") {
      const configHost = document.getElementById("moduleRedPacketConfig");
      const mainCol = configHost?.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      if (sections.length < 2) return;
      sections[0].classList.add("modal-card-source");
      sections[1].classList.add("modal-template-host");

      const delayMs = Number(document.getElementById("redPacketSendDelayMs")?.value || 0);
      const preLines = firstLines(document.getElementById("redPacketPreClickMessages")?.value || "", 99);
      const tplCards = document.querySelectorAll("#redPacketTemplates .template-card");
      const enabledCount = Array.from(tplCards).filter((c) => c.querySelector('[data-field="enabled"]')?.checked).length;

      const host = ensureSummaryHost(mainCol, sections[0], "moduleRedPacket");
      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>发送与延迟策略</span><small class="hint">点击卡片编辑抢红包延迟与自动发言候选</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "red_packet",
              title: "发言与延迟策略",
              desc: "控制按钮模板首次点击后的随机发言候选与二次点击延迟。",
              pillText: delayMs > 0 ? `延迟 ${delayMs} ms` : "立即触发",
              pillKind: "accent",
              chips: [`发言候选 ${preLines.length} 条`, preLines[0] ? `例: ${clipText(preLines[0], 24)}` : "暂无候选文案"],
              sectionIdx: 0,
            })}
          </div>
        </div>
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>红包与抽奖匹配规则</span><small class="hint">${tplCards.length} 条规则 · ${enabledCount} 条启用 · 点击卡片弹出编辑</small></div>
          ${renderTemplateSummaryGrid(
            viewId,
            "#redPacketTemplates",
            (card, idx) => {
              const name = card.querySelector('[data-field="name"]')?.value?.trim() || `规则模板 #${idx + 1}`;
              const enabled = Boolean(card.querySelector('[data-field="enabled"]')?.checked);
              const autoSpeak = Boolean(card.querySelector('[data-field="send_message_before_click"]')?.checked);
              const kws = firstLines(card.querySelector('[data-field="trigger_keywords"]')?.value || "", 3);
              const btns = firstLines(card.querySelector('[data-field="button_texts"]')?.value || "", 2);
              const markers = countLines(card.querySelector('[data-field="passphrase_markers"]')?.value || "");
              return {
                icon: "red_packet",
                title: name,
                enabled,
                pillText: enabled ? "启用" : "停用",
                pillKind: enabled ? "ok" : "",
                desc: autoSpeak ? "已开启首次抢后自动发言" : "标准口令 / 按钮自动领取",
                chips: [
                  kws.length ? `关键词: ${kws.join(" / ")}` : "未设关键词",
                  btns.length ? `按钮: ${btns.join(" / ")}` : "",
                  markers ? `口令标记 ${markers} 条` : "",
                ],
              };
            },
            "还没有模板。点击上方「新增模板」创建第一个红包或抽奖规则。",
          )}
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleSendRedPacket") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      if (sections[0]) sections[0].classList.add("modal-card-source");
      if (sections[1]) sections[1].classList.add("modal-template-host");
      const host = ensureSummaryHost(mainCol, sections[0], "moduleSendRedPacket");
      const strictCount = countLines(formVal("sendRedPacketSettingsForm", "strict_min_packet_group_ids"));
      const tplCount = document.querySelectorAll("#sendRedPacketTemplates .template-card").length;

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>基础风控</span><small class="hint">点击卡片在弹窗中编辑金额下限与状态文件</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "send_red_packet",
              title: "风控与基础参数",
              desc: "控制同时在线红包数量、普通/严格群单包金额下限与持久化路径。",
              pillText: `最多 ${formVal("sendRedPacketSettingsForm", "max_active_packets") || 20} 个活跃`,
              pillKind: "accent",
              chips: [
                `ID ${formVal("sendRedPacketSettingsForm", "id_length") || 6} 位`,
                `普通下限 ${formVal("sendRedPacketSettingsForm", "min_packet_amount") || 2}`,
                `严格下限 ${formVal("sendRedPacketSettingsForm", "strict_min_packet_amount") || 101} (${strictCount} 群)`,
              ],
              sectionIdx: 0,
            })}
          </div>
        </div>
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>红包玩法模板</span><small class="hint">共 ${tplCount} 个玩法 · 点击卡片弹出编辑</small></div>
          ${renderTemplateSummaryGrid(
            viewId,
            "#sendRedPacketTemplates",
            (card, idx) => {
              const name = card.querySelector('[data-field="name"]')?.value?.trim() || `玩法模板 #${idx + 1}`;
              const enabled = Boolean(card.querySelector('[data-field="enabled"]')?.checked);
              const type = card.querySelector('[data-field="type"]')?.value || "lucky_text";
              const cmds = firstLines(card.querySelector('[data-field="command_prefixes"]')?.value || "", 3);
              const maxCount = card.querySelector('[data-field="max_packet_count"]')?.value || 100;
              return {
                icon: "send_red_packet",
                title: name,
                enabled,
                pillText: type === "math_quiz" ? "算术题" : "拼手气口令",
                pillKind: enabled ? "ok" : "",
                desc: `单包最大数量 ${maxCount} 个`,
                chips: cmds.length ? cmds : ["未配置指令"],
              };
            },
            "还没有发红包模板。点击上方「新增模板」创建第一种红包玩法。",
          )}
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleAiReply") {
      const mainCol = viewEl.querySelector(".workspace-main");
      const asideCol = viewEl.querySelector(".workspace-aside");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      const capCard = asideCol?.querySelector(".aside-card");
      if (capCard) {
        capCard.classList.add("section-card", "modal-card-source");
        capCard.dataset.modalTitle = "能力开关";
        capCard.dataset.modalSubtitle = "控制联网搜索、思考摘要和 /msg 原始信息查看";
      }
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const allModalCards = capCard ? [...sections, capCard] : sections;

      const host = ensureSummaryHost(mainCol, sections[0], "moduleAiReply");
      const prompt = formVal("replySettingsForm", "system_prompt");
      const cmds = firstLines(formVal("replySettingsForm", "command_prefixes"), 3);
      const wakes = countLines(formVal("replySettingsForm", "wake_words"));
      const webOn = Boolean(formVal("replySettingsForm", "web_search"));
      const summaryOn = Boolean(formVal("replySettingsForm", "reasoning_summary"));
      const msgOn = Boolean(formVal("replySettingsForm", "message_info_enabled"));
      const enabledCaps = [webOn && "联网搜索", summaryOn && "思考摘要", msgOn && "/msg 查看"].filter(Boolean);

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>回复与推理配置</span><small class="hint">点击任意卡片在弹窗中编辑详细参数</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "ai_reply",
              title: "人设与触发词",
              desc: prompt ? clipText(prompt, 64) : "未设置自定义系统提示词",
              pillText: `${cmds.length + wakes} 项触发`,
              pillKind: "accent",
              chips: [...cmds, wakes ? `唤醒词 ${wakes} 个` : ""].filter(Boolean),
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "stats",
              title: "推理与生成参数",
              desc: "控制上下文条数、超时、最大输出、Temperature 与思考深度。",
              pillText: `Reasoning: ${formVal("replySettingsForm", "reasoning_effort") || "medium"}`,
              pillKind: "ok",
              chips: [
                `上下文 ${formVal("replySettingsForm", "context_limit") || 0} 条`,
                `Tokens ${formVal("replySettingsForm", "max_tokens") || "-"}`,
                `Temp ${formVal("replySettingsForm", "temperature") || "-"}`,
                `超时 ${formVal("replySettingsForm", "timeout_seconds") || "-"}s`,
              ],
              sectionIdx: 1,
            })}
            ${
              capCard
                ? makeSummaryCardHtml({
                    icon: "spark",
                    title: "能力开关",
                    desc: "管理联网检索、推理摘要展示与 /msg 原始元信息查看。",
                    pillText: `${enabledCaps.length}/3 已开启`,
                    pillKind: enabledCaps.length ? "ok" : "",
                    chips: enabledCaps.length ? enabledCaps : ["全部未开启"],
                    sectionIdx: 2,
                  })
                : ""
            }
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, allModalCards, viewId);
      return;
    }

    if (viewId === "moduleUserProfile") {
      const form = document.getElementById("userProfileSettingsForm");
      if (!form) return;
      const sections = Array.from(form.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(form, sections[0], "moduleUserProfile");
      const cmds = firstLines(formVal("userProfileSettingsForm", "command_prefixes"), 4);
      const stylePrompt = formVal("userProfileSettingsForm", "style_prompt");

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>画像参数配置</span><small class="hint">点击卡片在弹窗中编辑抽样预算与风格</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "user_profile",
              title: "抽样与模型预算",
              desc: "配置触发命令、样本上下限及 AI 耗时与长度上限。",
              pillText: `默认 ${formVal("userProfileSettingsForm", "default_sample_size") || 40} 条样本`,
              pillKind: "ok",
              chips: [
                ...cmds.slice(0, 3),
                `范围 ${formVal("userProfileSettingsForm", "min_sample_size") || 3}-${formVal("userProfileSettingsForm", "max_sample_size") || 2000}`,
                `Tokens ${formVal("userProfileSettingsForm", "max_tokens") || "-"}`,
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "spark",
              title: "画像写作风格与进度反馈",
              desc: stylePrompt ? clipText(stylePrompt, 68) : "使用默认写作风格与安全边界",
              pillText: "原地进度更新",
              pillKind: "accent",
              chips: ["结构化 JSON", "Telegram HTML"],
              sectionIdx: 1,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleAiImage") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(mainCol, sections[0], "moduleAiImage");
      const drawCmds = firstLines(formVal("imageSettingsForm", "command_prefixes"), 3);

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>生图配置</span><small class="hint">点击卡片在弹窗中编辑画质、比例与触发指令</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "ai_image",
              title: "默认画质与发送策略",
              desc: "配置默认分辨率、画面比例、质量与原图/预览发送模式。",
              pillText: `${formVal("imageSettingsForm", "size") || "1K"} · ${formVal("imageSettingsForm", "ratio") || "auto"}`,
              pillKind: "ok",
              chips: [
                `质量: ${formVal("imageSettingsForm", "quality") || "standard"}`,
                `发送: ${formVal("imageSettingsForm", "send_mode") || "auto"}`,
                `超时 ${formVal("imageSettingsForm", "timeout_seconds") || "-"}s`,
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "command",
              title: "群聊触发命令",
              desc: "管理群聊作图、切换尺寸、比例、发送模式与生图模型的指令前缀。",
              pillText: `${drawCmds.length} 个主命令`,
              pillKind: "accent",
              chips: [
                ...drawCmds,
                `尺寸指令 ${countLines(formVal("imageSettingsForm", "size_commands"))}`,
                `模型指令 ${countLines(formVal("imageSettingsForm", "model_commands"))}`,
              ],
              sectionIdx: 1,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleAiDecrypt") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      if (sections[0]) sections[0].classList.add("modal-card-source");
      if (sections[1]) sections[1].classList.add("modal-template-host");
      const host = ensureSummaryHost(mainCol, sections[0], "moduleAiDecrypt");
      const tplCount = document.querySelectorAll("#decryptTemplates .template-card").length;

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>解题推理</span><small class="hint">点击卡片编辑超时、清晰度与去重路径</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "ai_decrypt",
              title: "解题推理与去重设置",
              desc: "命中解密模板后调用 AI 视觉解题并自动发送最终答案。",
              pillText: `清晰度 ${formVal("decryptSettingsForm", "image_detail") || "original"}`,
              pillKind: "accent",
              chips: [
                `超时 ${formVal("decryptSettingsForm", "timeout_seconds") || 120}s`,
                `Tokens ${formVal("decryptSettingsForm", "max_tokens") || 512}`,
                `延迟 ${formVal("decryptSettingsForm", "send_delay_ms") || 0} ms`,
              ],
              sectionIdx: 0,
            })}
          </div>
        </div>
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>解密规则模板</span><small class="hint">共 ${tplCount} 条 · 点击卡片弹出编辑</small></div>
          ${renderTemplateSummaryGrid(
            viewId,
            "#decryptTemplates",
            (card, idx) => {
              const name = card.querySelector('[data-field="name"]')?.value?.trim() || `解密规则 #${idx + 1}`;
              const enabled = Boolean(card.querySelector('[data-field="enabled"]')?.checked);
              const reqMedia = Boolean(card.querySelector('[data-field="require_media"]')?.checked);
              const kws = firstLines(card.querySelector('[data-field="trigger_keywords"]')?.value || "", 3);
              return {
                icon: "ai_decrypt",
                title: name,
                enabled,
                pillText: reqMedia ? "需带图片" : "支持纯文本",
                pillKind: enabled ? "ok" : "",
                desc: kws.length ? `需全部命中：${kws.join(" + ")}` : "尚未填写触发关键词",
                chips: kws,
              };
            },
            "还没有解密模板。点击上方「新增模板」创建第一条解密规则。",
          )}
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleGif") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(mainCol, sections[0], "moduleGif");
      const cmds = firstLines(formVal("gifSettingsForm", "command_prefixes"), 4);

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>转码参数</span><small class="hint">点击卡片在弹窗中编辑截取参数与输出目录</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "gif",
              title: "截取与转码参数",
              desc: "回复视频/GIF/WebP 触发截取，支持自然语言时间段与体积控制。",
              pillText: `最长 ${formVal("gifSettingsForm", "max_seconds") || 15}s · ${formVal("gifSettingsForm", "fps") || 12} FPS`,
              pillKind: "ok",
              chips: [
                ...cmds.slice(0, 3),
                `宽度 ${formVal("gifSettingsForm", "width") || "auto"}`,
              ],
              sectionIdx: 0,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleWordCloud") {
      const form = document.getElementById("wordCloudSettingsForm");
      if (!form) return;
      const sections = Array.from(form.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(form, sections[0], "moduleWordCloud");
      const cmds = firstLines(formVal("wordCloudSettingsForm", "command_prefixes"), 3);
      const stops = countLines(formVal("wordCloudSettingsForm", "stop_words"));

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>词云配置</span><small class="hint">点击卡片在弹窗中编辑统计范围与分词规则</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "word_cloud",
              title: "统计范围与画布尺寸",
              desc: "配置每群默认统计条数上下限与输出词云图片分辨率。",
              pillText: `默认 ${formVal("wordCloudSettingsForm", "default_limit") || 500} 条`,
              pillKind: "ok",
              chips: [
                `${formVal("wordCloudSettingsForm", "width") || 1200}×${formVal("wordCloudSettingsForm", "height") || 800}px`,
                `范围 ${formVal("wordCloudSettingsForm", "min_limit") || 10}-${formVal("wordCloudSettingsForm", "max_limit") || 5000}`,
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "command",
              title: "命令与分词过滤",
              desc: "配置触发词、忽略命令前缀、额外停用词及触发后删命令。",
              pillText: formVal("wordCloudSettingsForm", "delete_command") ? "触发后删命令" : "保留命令",
              pillKind: "accent",
              chips: [...cmds, `停用词 ${stops} 个`],
              sectionIdx: 1,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleCheckin") {
      const mainCol = viewEl.querySelector(".workspace-main");
      const tasksList = document.getElementById("checkinTasks");
      if (!mainCol || !tasksList) return;
      const host = ensureSummaryHost(mainCol, tasksList, "moduleCheckin");
      const cards = tasksList.querySelectorAll(".template-card");
      const enabledCount = Array.from(cards).filter((c) => c.querySelector('[data-field="enabled"]')?.checked).length;

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>定时签到任务</span><small class="hint">${cards.length} 个任务 · ${enabledCount} 个启用 · 点击卡片弹出编辑 Cron 与发送内容</small></div>
          ${renderTemplateSummaryGrid(
            viewId,
            "#checkinTasks",
            (card, idx) => {
              const name = card.querySelector('[data-field="name"]')?.value?.trim() || `签到任务 #${idx + 1}`;
              const enabled = Boolean(card.querySelector('[data-field="enabled"]')?.checked);
              const target = card.querySelector('[data-field="target"]')?.value?.trim() || "未填目标";
              const cronText = card.querySelector(".cron-summary")?.textContent?.trim() || card.querySelector('[data-field="cron"]')?.value?.trim() || "";
              const message = card.querySelector('[data-field="message"]')?.value?.trim() || "";
              const invalid = card.querySelector(".cron-summary")?.classList.contains("invalid");
              return {
                icon: "checkin",
                title: name,
                enabled,
                pillText: invalid ? "Cron 有误" : enabled ? "运行中" : "已暂停",
                pillKind: invalid ? "warn" : enabled ? "ok" : "",
                desc: cronText || "未配置 Cron 排程",
                chips: [`目标: ${clipText(target, 24)}`, message ? `内容: ${clipText(message, 24)}` : ""],
              };
            },
            "还没有签到任务。点击上方「新增签到」创建第一个定时消息。",
          )}
        </div>
      `;
      bindSummaryHubClicks(host, [], viewId);
      return;
    }

    if (viewId === "moduleAutoForward") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(mainCol, sections[0], "moduleAutoForward");
      const chips = [
        ...firstLines(formVal("autoForwardSettingsForm", "command_prefixes"), 1),
        ...firstLines(formVal("autoForwardSettingsForm", "copy_text_command_prefixes"), 1),
        ...firstLines(formVal("autoForwardSettingsForm", "quote_command_prefixes"), 1),
        ...firstLines(formVal("autoForwardSettingsForm", "link_command_prefixes"), 1),
      ];

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>转发映射</span><small class="hint">点击卡片编辑四种转发模式对应的命令前缀</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "auto_forward",
              title: "转发模式命令映射",
              desc: "回复某条消息后发送对应命令，支持原生转发、复制文本、引用包装与公开链接。",
              pillText: formVal("autoForwardSettingsForm", "delete_command") ? "成功后删命令" : "保留触发命令",
              pillKind: "ok",
              chips: chips.length ? chips : ["未配置指令"],
              sectionIdx: 0,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleMagnetImport") {
      const form = document.getElementById("magnetImportSettingsForm");
      if (!form) return;
      const subtabBar = viewEl.querySelector('.subtab-bar[data-tab-group="magnetImport"]');
      if (subtabBar) subtabBar.classList.add("hidden");
      const sections = Array.from(form.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(form, sections[0], "moduleMagnetImport");

      const watchCount = countLines(formVal("magnetImportSettingsForm", "watch_chats"));
      const chOn = Boolean(formVal("magnetImportSettingsForm", "channel_enabled"));
      const avOn = Boolean(formVal("magnetImportSettingsForm", "avdb_enabled"));
      const exOn = Boolean(formVal("magnetImportSettingsForm", "channel_export_enabled"));
      const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
      const wdIdx = Number(formVal("magnetImportSettingsForm", "channel_export_weekday") || 0);

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>导入通道与同步任务</span><small class="hint">点击卡片在弹窗中编辑详细配置，常用同步操作可直接在卡片上触发</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "magnet_import",
              title: "群聊 CSV 监听与连接",
              desc: "监听指定群 CSV 数据并导入 MagnetBoard，支持断点续传与手动指令。",
              pillText: `监听 ${watchCount} 群`,
              pillKind: watchCount ? "ok" : "warn",
              chips: [
                clipText(formVal("magnetImportSettingsForm", "api_base_url") || "未设地址", 32),
                `上限 ${formVal("magnetImportSettingsForm", "max_file_size_mb") || 0}MB`,
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "rex_widget_sync",
              title: "频道来源",
              desc: document.getElementById("magnetChannelLast")?.textContent?.trim() || "监听频道帖子按番号提取链接并补封面。",
              pillText: chOn ? "已启用" : "未启用",
              pillKind: chOn ? "ok" : "",
              chips: [
                document.getElementById("magnetChannelCount")?.textContent?.trim() || "",
                document.getElementById("magnetChannelCursor")?.textContent?.trim() || "",
              ],
              sectionIdx: 1,
              actionButtonsHtml: `
                <button type="button" data-proxy-click="magnetChannelFullScan">全量提取频道</button>
                <button type="button" class="danger" data-proxy-click="magnetChannelRebuild">重建频道记录</button>
              `,
            })}
            ${makeSummaryCardHtml({
              icon: "hardware",
              title: "AVDB 资源包",
              desc: document.getElementById("magnetAvdbLast")?.textContent?.trim() || "自动轮询并导入最新 GitHub release 打包资源。",
              pillText: avOn ? `每 ${formVal("magnetImportSettingsForm", "avdb_interval_hours") || 6}h` : "未启用",
              pillKind: avOn ? "ok" : "",
              chips: [
                document.getElementById("magnetAvdbTag")?.textContent?.trim() || "",
                document.getElementById("magnetAvdbCount")?.textContent?.trim() || "",
              ],
              sectionIdx: 2,
              actionButtonsHtml: `
                <button type="button" data-proxy-click="magnetAvdbCheck">立即检查</button>
                <button type="button" data-proxy-click="magnetAvdbUpdate">更新已有</button>
                <button type="button" class="danger" data-proxy-click="magnetAvdbRebuild">重建</button>
              `,
            })}
            ${makeSummaryCardHtml({
              icon: "upload",
              title: "每周全量导出",
              desc: document.getElementById("magnetExportLast")?.textContent?.trim() || "按计划自动导出频道 CSV 并发送到指定群组。",
              pillText: exOn ? `${weekdays[wdIdx] || "周一"} ${formVal("magnetImportSettingsForm", "channel_export_time") || ""}` : "未启用",
              pillKind: exOn ? "ok" : "",
              chips: [document.getElementById("magnetExportCursor")?.textContent?.trim() || ""],
              sectionIdx: 3,
              actionButtonsHtml: `<button type="button" data-proxy-click="magnetChannelExportNow">立即导出并发送</button>`,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleRexWidgetSync") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(mainCol, sections[0], "moduleRexWidgetSync");
      const ignoreCount = countLines(formVal("rexWidgetSyncSettingsForm", "ignore_keys"));

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>同步连接配置</span><small class="hint">点击卡片在弹窗中编辑频道 ID、Hub 地址与过滤规则</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "rex_widget_sync",
              title: "频道与 Hub 连接配置",
              desc: "监听模块分享频道 .js 帖子并按版本号自动上传到 Rex Widget Hub 合集。",
              pillText: formVal("rexWidgetSyncSettingsForm", "collection_slug") || "未填合集",
              pillKind: "ok",
              chips: [
                clipText(formVal("rexWidgetSyncSettingsForm", "hub_base_url") || "未填 Hub", 34),
                `频道 ${formVal("rexWidgetSyncSettingsForm", "channel_chat") || "-"}`,
                ignoreCount ? `忽略 ${ignoreCount} 个 key` : "",
              ],
              sectionIdx: 0,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleQuote") {
      const mainCol = viewEl.querySelector(".workspace-main");
      if (!mainCol) return;
      const sections = Array.from(mainCol.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(mainCol, sections[0], "moduleQuote");
      const cmds = firstLines(formVal("quoteSettingsForm", "command_prefixes"), 3);

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>语录渲染配置</span><small class="hint">点击卡片在弹窗中编辑接口地址、画布尺寸与贴纸包</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "quote",
              title: "渲染接口与样式配置",
              desc: clipText(formVal("quoteSettingsForm", "api_url") || "未配置 quote-api 地址", 58),
              pillText: `${formVal("quoteSettingsForm", "width") || 512}×${formVal("quoteSettingsForm", "height") || 768}`,
              pillKind: "accent",
              chips: [
                ...cmds,
                formVal("quoteSettingsForm", "background_color") ? `底色 ${formVal("quoteSettingsForm", "background_color")}` : "",
                formVal("quoteSettingsForm", "sticker_set_short_name") ? `贴纸包 ${formVal("quoteSettingsForm", "sticker_set_short_name")}` : "未绑贴纸包",
              ],
              sectionIdx: 0,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }

    if (viewId === "moduleChatGames") {
      const form = document.getElementById("chatGamesSettingsForm");
      if (!form) return;
      const subtabBar = viewEl.querySelector('.subtab-bar[data-tab-group="chatGames"]');
      if (subtabBar) subtabBar.classList.add("hidden");
      const sections = Array.from(form.querySelectorAll(":scope > .section-card"));
      sections.forEach((s) => s.classList.add("modal-card-source"));
      const host = ensureSummaryHost(form, sections[0], "moduleChatGames");

      const luckyOn = Boolean(formVal("chatGamesSettingsForm", "lucky_enabled"));
      const emojiOn = Boolean(formVal("chatGamesSettingsForm", "emoji_enabled"));
      const decodeOn = Boolean(formVal("chatGamesSettingsForm", "decode_enabled"));

      host.innerHTML = `
        <div class="summary-hub-group">
          <div class="summary-hub-label"><span>小游戏玩法与题库</span><small class="hint">点击任意玩法卡片在弹窗中编辑开关、奖励与题库</small></div>
          <div class="summary-card-grid">
            ${makeSummaryCardHtml({
              icon: "spark",
              title: "今日幸运词",
              desc: "群友自然发言命中当日隐藏词时自动回复加分指令。",
              pillText: luckyOn ? "已启用" : "未启用",
              pillKind: luckyOn ? "ok" : "",
              chips: [
                `奖励 ${formVal("chatGamesSettingsForm", "lucky_reward_text") || "+100"}`,
                `词库 ${countLines(formVal("chatGamesSettingsForm", "lucky_words"))} 词`,
                `每群每日 ${formVal("chatGamesSettingsForm", "lucky_daily_limit_per_chat") || 0} 次`,
              ],
              sectionIdx: 0,
            })}
            ${makeSummaryCardHtml({
              icon: "chat_games",
              title: "Emoji 图谜",
              desc: "通过 Emoji 组合提示成语或热词，支持首中或随机抽取赢家。",
              pillText: emojiOn ? "已启用" : "未启用",
              pillKind: emojiOn ? "ok" : "",
              chips: [
                `${formVal("chatGamesSettingsForm", "emoji_duration_seconds") || 60}s`,
                `奖励 ${formVal("chatGamesSettingsForm", "emoji_reward_text") || "+100"}`,
                `题库 ${countLines(formVal("chatGamesSettingsForm", "emoji_items"))} 题`,
              ],
              sectionIdx: 1,
            })}
            ${makeSummaryCardHtml({
              icon: "ai_decrypt",
              title: "乱码解码",
              desc: "生成视觉干扰/乱码短句图片，最快还原原文者获胜。",
              pillText: decodeOn ? "已启用" : "未启用",
              pillKind: decodeOn ? "ok" : "",
              chips: [
                `${formVal("chatGamesSettingsForm", "decode_duration_seconds") || 60}s`,
                `奖励 ${formVal("chatGamesSettingsForm", "decode_reward_text") || "+100"}`,
                `短句 ${countLines(formVal("chatGamesSettingsForm", "decode_phrases"))} 条`,
              ],
              sectionIdx: 2,
            })}
            ${makeSummaryCardHtml({
              icon: "hardware",
              title: "状态文件与输出目录",
              desc: "记录每日次数限制与临时生成的游戏图片目录。",
              pillText: "持久化路径",
              chips: [clipText(formVal("chatGamesSettingsForm", "state_store") || "-", 34)],
              sectionIdx: 3,
            })}
          </div>
        </div>
      `;
      bindSummaryHubClicks(host, sections, viewId);
      return;
    }
  }

  function bindSummaryHubClicks(host, sections, viewId) {
    if (host.dataset.hubBound === "1") {
      host._modalSections = sections;
      return;
    }
    host._modalSections = sections;
    host.dataset.hubBound = "1";

    host.addEventListener("click", (event) => {
      if (event.target.closest("[data-stop-card]")) return;

      const proxyBtn = event.target.closest("[data-proxy-click]");
      if (proxyBtn) {
        event.stopPropagation();
        document.getElementById(proxyBtn.dataset.proxyClick)?.click();
        return;
      }

      const removeBtn = event.target.closest("[data-proxy-tpl-remove]");
      if (removeBtn) {
        event.stopPropagation();
        const list = document.querySelector(removeBtn.dataset.proxyTplRemove);
        const idx = Number(removeBtn.dataset.templateIdx);
        const card = list?.querySelectorAll(":scope > .template-card")?.[idx];
        card?.querySelector('[data-action^="remove-"]')?.click();
        markViewDirty(viewId);
        renderSummaryHubForView(viewId);
        return;
      }

      const tplCard = event.target.closest("[data-open-template]");
      if (tplCard) {
        const list = document.querySelector(tplCard.dataset.openTemplate);
        const idx = Number(tplCard.dataset.templateIdx);
        const card = list?.querySelectorAll(":scope > .template-card")?.[idx];
        if (card) {
          const title = card.querySelector('[data-field="name"]')?.value?.trim() || "编辑规则卡片";
          openCardModal(card, { title, subtitle: "修改字段后点击下方保存配置立即生效", icon: viewIconMap[viewId] || "modules" });
        }
        return;
      }

      const secCard = event.target.closest("[data-open-section-idx], [data-open-section]");
      if (secCard) {
        let target = null;
        if (secCard.dataset.openSection) {
          target = document.getElementById(secCard.dataset.openSection);
        } else {
          const idx = Number(secCard.dataset.openSectionIdx);
          target = host._modalSections?.[idx] || null;
        }
        if (target) openCardModal(target);
      }
    });

    host.addEventListener("change", (event) => {
      const toggle = event.target.closest("[data-proxy-tpl-toggle]");
      if (!toggle) return;
      const list = document.querySelector(toggle.dataset.proxyTplToggle);
      const idx = Number(toggle.dataset.templateIdx);
      const card = list?.querySelectorAll(":scope > .template-card")?.[idx];
      const realCheckbox = card?.querySelector('[data-field="enabled"]');
      if (realCheckbox) {
        realCheckbox.checked = toggle.checked;
        markViewDirty(viewId);
        renderSummaryHubForView(viewId);
      }
    });

    host.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const card = event.target.closest(".summary-card, .template-summary-card");
      if (!card || event.target !== card) return;
      event.preventDefault();
      card.click();
    });
  }

  /* ========================================================================
     7. Settings Center Live Badges & Search
     ======================================================================== */

  function updateSettingsStudioBadges(groupIds = null) {
    const groupsBadge = document.getElementById("settingsGroupsBadge");
    const preview = document.getElementById("settingsGroupsPreview");
    const ids = Array.isArray(groupIds) ? groupIds : typeof selectedGroups === "function" ? selectedGroups() : [];
    if (groupsBadge) {
      groupsBadge.textContent = `${ids.length} 个已选`;
      groupsBadge.className = `summary-pill ${ids.length ? "ok" : ""}`;
    }
    if (preview) {
      if (!ids.length) {
        preview.innerHTML = '<span class="summary-chip">未限制 · 监听全部可见群</span>';
      } else {
        preview.innerHTML =
          ids
            .slice(0, 4)
            .map((id) => {
              const meta = typeof groupMetaForId === "function" ? groupMetaForId(id) : { title: id };
              return `<span class="summary-chip">${escapeHtml(meta.title || id)}</span>`;
            })
            .join("") + (ids.length > 4 ? `<span class="summary-chip">+${ids.length - 4}</span>` : "");
      }
    }

    const appBadge = document.getElementById("settingsAppearanceBadge");
    if (appBadge) {
      appBadge.textContent = `${currentWallpaperLabel()} · ${ambientEffectLabel(studioState.prefs.appearance.ambientEffect)}`;
    }

    const sidebarBadge = document.getElementById("settingsSidebarBadge");
    if (sidebarBadge) {
      const layout = studioState.prefs.sidebarLayout || [];
      const count = layoutAssignedSet().size;
      sidebarBadge.textContent = `${layout.length} 组 · ${count} 项`;
    }

    const aiBadge = document.getElementById("settingsAiSummaryBadge");
    if (aiBadge && state.ai?.providers?.reply) {
      const reply = state.ai.providers.reply;
      aiBadge.textContent = reply.model ? `${reply.model}${reply.has_api_key ? " · 已配 Key" : ""}` : "未配置模型";
      aiBadge.className = `summary-pill ${reply.has_api_key ? "ok" : "warn"}`;
    }
  }

  function bindSettingsHubEvents() {
    document.getElementById("settingsHubSearch")?.addEventListener("input", (event) => {
      const q = (event.currentTarget.value || "").trim().toLowerCase();
      document.querySelectorAll("#settingsHubGroups .summary-card").forEach((card) => {
        const hay = `${card.dataset.searchTerms || ""} ${card.textContent || ""}`.toLowerCase();
        card.classList.toggle("hidden", Boolean(q) && !hay.includes(q));
      });
    });

    document.querySelectorAll("#settings [data-open-section]").forEach((card) => {
      const open = () => {
        const target = document.getElementById(card.dataset.openSection);
        if (target) openCardModal(target, { saveBtnId: "saveGroups", saveLabel: "保存监听群组" });
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });

    document.getElementById("glassModalBackdrop")?.addEventListener("click", () => closeCardModal(true));
  }

  /* ========================================================================
     8. Public Hooks Called by app.js
     ======================================================================== */

  window.uiStudio = {
    openAppearanceModal,
    closeAppearanceModal,
    closeCardModal,
    handleEscape() {
      if (closeAppearanceModal()) return true;
      if (closeCardModal(true)) return true;
      return false;
    },
    onViewShown(viewId) {
      closeCardModal(false);
      if (viewId === "sidebarArrange") renderArrangeStudio();
      renderSummaryHubForView(viewId);
    },
    onViewDataRendered(viewId) {
      renderSummaryHubForView(viewId);
    },
    onModulesUpdated() {
      renderSidebarFromLayout();
      if (state.currentView) renderSummaryHubForView(state.currentView);
    },
    onAiUpdated() {
      updateSettingsStudioBadges();
      if (["aiServices", "moduleAiReply", "moduleAiImage"].includes(state.currentView)) {
        renderSummaryHubForView(state.currentView);
      }
    },
    onSettingsUpdated(groupIds) {
      updateSettingsStudioBadges(groupIds);
    },
    onTemplateAdded(viewId, cardEl) {
      renderSummaryHubForView(viewId);
      if (cardEl) {
        const title = cardEl.querySelector('[data-field="name"]')?.value?.trim() || "新建规则";
        openCardModal(cardEl, { title, subtitle: "填写新规则详情并点击保存", icon: viewIconMap[viewId] || "modules" });
      }
    },
    onSaveSucceeded(viewId) {
      if (studioState.activeModal) {
        closeCardModal(false);
      }
      window.setTimeout(() => {
        renderSummaryHubForView(viewId || state.currentView);
        updateSettingsStudioBadges();
      }, 40);
    },
    onThemeChanged(theme) {
      studioState.prefs.theme = theme;
      applyAllPreferences(true);
    },
    onDensityChanged(density) {
      studioState.prefs.density = density;
      syncAppearanceModalControls();
      schedulePrefsSave();
    },
    onSidebarToggled(collapsed) {
      studioState.prefs.sidebarCollapsed = Boolean(collapsed);
      schedulePrefsSave();
    },
  };

  /* ========================================================================
     9. Bootstrap
     ======================================================================== */

  function bootstrap() {
    if (typeof renderStaticIcons === "function") renderStaticIcons();
    ambientEngine.init();
    bindAppearanceModalEvents();
    bindArrangeStudioEvents();
    bindSettingsHubEvents();
    void hydratePrefs();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
})();
