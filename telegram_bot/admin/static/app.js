const GROUP_NAME_CACHE_KEY = "telegrambot.settings.groupNameCache.v1";
const THEME_STORAGE_KEY = "telegrambot.admin.theme.v1";
const DENSITY_STORAGE_KEY = "telegrambot.admin.density.v1";
const SIDEBAR_STORAGE_KEY = "telegrambot.admin.sidebar.v1";

const state = {
  status: null,
  settings: null,
  groups: [],
  checkinTargets: [],
  modules: [],
  metricHistory: [],
  lastUsageData: null,
  chartWindow: "15m",
  logAutoRefresh: true,
  logAutoScroll: true,
  logWordWrap: true,
  logSourceTab: "live",
  logClearedCursor: "",
  logFilesList: [],
  logRefreshIntervalSeconds: 1,
  logsViewingFile: false,
  recentLogRecords: [],
  logFileContent: "",
  logLevelFilter: "ALL",
  logSearchQuery: "",
  activeLogFile: "",
  moduleCategoryFilter: "all",
  moduleStatusFilter: "all",
  moduleSearchQuery: "",
  groupSearchQuery: "",
  dirtyViews: new Set(),
  currentView: "dashboard",
  imageSettingsBaseline: null,
  groupNameCache: loadGroupNameCache(),
};

const METRIC_HISTORY_KEY = "telegrambot.dashboard.metricHistory.v1";
const LOG_REFRESH_INTERVAL_KEY = "telegrambot.logs.refreshIntervalSeconds.v1";
const DEFAULT_LOG_REFRESH_INTERVAL_SECONDS = 1;
const MIN_LOG_REFRESH_INTERVAL_SECONDS = 0.1;
const METRIC_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const METRIC_MAX_POINTS = 2500;
const CHART_WINDOWS = {
  "15m": 15 * 60 * 1000,
  "30m": 30 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "2h": 2 * 60 * 60 * 1000,
  all: Infinity,
};

const ICONS = {
  dashboard: '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="11" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="17" width="7" height="3" rx="1.5"/>',
  modules: '<path d="M5 4h6l2 3h6v13H5z"/><path d="M8 11h8M8 15h5"/>',
  red_packet: '<path d="M6 7h12v13H6z"/><path d="M6 10h12"/><path d="m9 7 3-3 3 3"/><circle cx="12" cy="14" r="2.5"/>',
  send_red_packet: '<path d="M5 8h14v11H5z"/><path d="M5 11h14"/><path d="M12 8V5"/><path d="m9 5 3-3 3 3"/><path d="M9 15h6"/><path d="M12 13v4"/>',
  ai_reply: '<path d="M5 6h14v9H9l-4 4z"/><path d="M9 10h6M9 13h4"/><circle cx="17" cy="7" r="2"/>',
  user_profile: '<circle cx="10" cy="8" r="3"/><path d="M4.5 18c.8-3.2 2.7-4.8 5.5-4.8s4.7 1.6 5.5 4.8"/><path d="m18 5 .7 1.8L20.5 7.5l-1.8.7L18 10l-.7-1.8-1.8-.7 1.8-.7z"/>',
  ai_image: '<rect x="4" y="5" width="16" height="14" rx="3"/><circle cx="15.5" cy="9.5" r="1.7"/><path d="m6.5 16 4-4 3 3 2-2 2.5 3"/>',
  ai_decrypt: '<path d="M7 10V7a5 5 0 0 1 10 0v3"/><rect x="5" y="10" width="14" height="10" rx="3"/><path d="M12 14v3"/><path d="M9 4.8 7.5 3.3M15 4.8l1.5-1.5M12 3V1.5"/>',
  gif: '<rect x="4" y="5" width="16" height="14" rx="3"/><path d="M9 10v4h2.5M14 10v4M17 10h-2v4"/>',
  word_cloud: '<path d="M7 17.5h10a4 4 0 0 0 .7-7.9A5.5 5.5 0 0 0 7.1 8.2 4.8 4.8 0 0 0 7 17.5z"/><path d="M8 13h8M9.5 10.5h5M10.5 15.5h3"/>',
  checkin: '<path d="M7 4v4M17 4v4"/><rect x="4" y="6" width="16" height="14" rx="3"/><path d="M8 13l3 3 5-6"/>',
  auto_forward: '<path d="M5 7h8a5 5 0 0 1 5 5v1"/><path d="m15 10 3 3 3-3"/><path d="M19 17H8a3 3 0 0 1-3-3v-1"/><path d="m8 10-3 3 3 3"/>',
  rex_widget_sync: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M17.5 14v7"/><path d="m14.5 18 3 3 3-3"/>',
  magnet_import: '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M7 4h3v7a2 2 0 0 0 4 0V4h3"/><path d="M12 17v4"/><path d="m9 19 3 3 3-3"/>',
  quote: '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-4 4z"/><path d="M8.5 9.5h2v3h-2zM13.5 9.5h2v3h-2z"/>',
  chat_games: '<path d="M7 9h10a4 4 0 0 1 3.8 5.3l-.7 2.1a2.2 2.2 0 0 1-3.7.8L14.8 16H9.2l-1.6 1.2a2.2 2.2 0 0 1-3.7-.8l-.7-2.1A4 4 0 0 1 7 9z"/><path d="M8 12v3M6.5 13.5h3M15.5 12.5h.01M18 14.5h.01"/>',
  aiServices: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 3v3M17.5 4.5h3M5 17v2.5M3.75 18.25h2.5"/>',
  aiUsage: '<path d="M5 19V5"/><path d="M5 19h15"/><path d="M8 15l3-4 3 2 4-6"/><circle cx="11" cy="11" r="1.5"/><circle cx="18" cy="7" r="1.5"/>',
  logs: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4"/>',
  chevronUp: '<path d="m6 15 6-6 6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20.2 14.8A8.5 8.5 0 0 1 9.2 3.8a8.5 8.5 0 1 0 11 11z"/>',
  device: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  hardware: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  trend: '<path d="M3 17l5-5 4 4 9-9"/><path d="M16 7h5v5"/>',
  speed: '<path d="M12 14l4-4"/><path d="M4.6 18a9 9 0 1 1 14.8 0"/>',
  stats: '<path d="M5 19V9M12 19V5M19 19v-7"/>',
  sidebarToggle: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  logout: '<path d="M10 17l5-5-5-5"/><path d="M15 12H4"/><path d="M14 4h5a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 19 20h-5"/>',
  power: '<path d="M12 3v8"/><path d="M6.6 6.6a8 8 0 1 0 10.8 0"/>',
  download: '<path d="M12 4v11"/><path d="m7.5 11.5 4.5 4.5 4.5-4.5"/><path d="M5 19h14"/>',
  upload: '<path d="M12 16V5"/><path d="m7.5 9.5 4.5-4.5 4.5 4.5"/><path d="M5 19h14"/>',
  palette: '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r="1.2"/><circle cx="12.5" cy="8" r="1.2"/><circle cx="16" cy="10.5" r="1.2"/><path d="M15 15.5a2 2 0 0 1 2 2 2.5 2.5 0 0 1-2.5 2.5"/>',
  arrange: '<rect x="3" y="4" width="7" height="7" rx="1.5"/><rect x="14" y="4" width="7" height="7" rx="1.5"/><rect x="3" y="13" width="7" height="7" rx="1.5"/><path d="M14 16.5h7M17.5 13v7"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  command: '<path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3 3 3 0 0 0-3-3H6a3 3 0 0 0-3 3 3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0 3 3h12a3 3 0 0 0 3-3 3 3 0 0 0-3-3z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  play: '<polygon points="6 4 20 12 6 20 6 4"/>',
  wrap: '<path d="M3 6h18"/><path d="M3 12h14a3 3 0 1 1 0 6h-4"/><polyline points="15 15 12 18 15 21"/><path d="M3 18h5"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/>',
  archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  arrowDown: '<path d="M12 5v14"/><polyline points="19 12 12 19 5 12"/>',
};

const MODULE_CATEGORY_KEYS = {
  red_packet: "interactive",
  send_red_packet: "interactive",
  chat_games: "interactive",
  ai_reply: "ai",
  user_profile: "ai",
  ai_image: "ai",
  ai_decrypt: "ai",
  gif: "media",
  word_cloud: "media",
  quote: "media",
  checkin: "media",
  auto_forward: "media",
  magnet_import: "sync",
  rex_widget_sync: "sync",
};

const CATEGORY_LABELS = {
  interactive: "互动与红包",
  ai: "AI 能力",
  media: "媒体与效率",
  sync: "同步与导入",
};

const viewIconMap = {
  dashboard: "dashboard",
  modules: "modules",
  moduleRedPacket: "red_packet",
  moduleSendRedPacket: "send_red_packet",
  moduleAiReply: "ai_reply",
  moduleUserProfile: "user_profile",
  moduleAiImage: "ai_image",
  moduleAiDecrypt: "ai_decrypt",
  moduleGif: "gif",
  moduleWordCloud: "word_cloud",
  moduleCheckin: "checkin",
  moduleAutoForward: "auto_forward",
  moduleMagnetImport: "magnet_import",
  moduleRexWidgetSync: "rex_widget_sync",
  moduleQuote: "quote",
  moduleChatGames: "chat_games",
  aiServices: "aiServices",
  aiUsage: "aiUsage",
  logs: "logs",
  settings: "settings",
  sidebarArrange: "arrange",
};
state.logRefreshIntervalSeconds = loadLogRefreshIntervalSeconds();
let logRefreshTimer = null;
let logRefreshInFlight = false;

const titles = {
  dashboard: ["仪表盘", "系统概览 · 实时监控"],
  modules: ["功能模块", "模块卡片 · 点击进入单独配置页"],
  moduleRedPacket: ["自动抢红包", "红包/抽奖模板 · 动态口令识别"],
  moduleSendRedPacket: ["发红包", "拼手气红包 · 预随机金额分配"],
  moduleAiReply: ["AI 自动回复", "群聊回复 · 触发词和模型参数"],
  moduleUserProfile: ["群友画像", "发言样本 · 人设速写 · 原消息论据"],
  moduleAiImage: ["AI 生图", "作图命令 · 尺寸比例和发送策略"],
  moduleAiDecrypt: ["AI 解密", "红包解密游戏 · 视觉识别和答案发送"],
  moduleGif: ["GIF动图", "视频/GIF 截取 · 多格式时间识别"],
  moduleWordCloud: ["词云", "当前群热词 · 图片统计"],
  moduleCheckin: ["自动签到", "定时发送 · 群组和 Bot 签到"],
  moduleAutoForward: ["自动转发", "回复转发 · ,re 快速回传"],
  moduleMagnetImport: ["磁力数据导入", "监听 CSV 分享 · 自动导入 MagnetBoard"],
  moduleRexWidgetSync: ["Rex 模块同步", "监听模块分享频道 · 自动更新 Hub 合集"],
  moduleQuote: ["语录贴纸", "回复消息 · 生成语录贴纸"],
  moduleChatGames: ["聊天小游戏", "幸运词 · Emoji 图谜 · 乱码解码"],
  aiServices: ["AI 服务配置", "连接服务 · 提供商类型和模型"],
  aiUsage: ["AI 用量统计", "Token 消耗 · 模型和功能分布"],
  logs: ["日志中心", "本体运行日志 · 自动滚动与归档检索"],
  settings: ["系统配置", "连接监听 · 外观背景 · 侧边栏编排"],
  sidebarArrange: ["编排", "自定义侧边栏分组、排序与显示项"],
};

const moduleViewMap = {
  red_packet: "moduleRedPacket",
  send_red_packet: "moduleSendRedPacket",
  ai_reply: "moduleAiReply",
  user_profile: "moduleUserProfile",
  ai_image: "moduleAiImage",
  ai_decrypt: "moduleAiDecrypt",
  gif: "moduleGif",
  word_cloud: "moduleWordCloud",
  checkin: "moduleCheckin",
  auto_forward: "moduleAutoForward",
  magnet_import: "moduleMagnetImport",
  rex_widget_sync: "moduleRexWidgetSync",
  quote: "moduleQuote",
  chat_games: "moduleChatGames",
};

document.querySelectorAll(".nav-item, .sub-nav-item").forEach((button) => {
  button.addEventListener("click", (event) => {
    const group = button.closest(".nav-group");
    if (button.classList.contains("nav-parent") && event.target.closest(".chevron")) {
      setGroupExpanded(group, !group.classList.contains("expanded"));
      return;
    }
    if (group) setGroupExpanded(group, true);
    showView(button.dataset.view);
  });
});

function waitForRestartAndReload() {
  const initialUptime = Number(state.status?.metrics?.uptime_seconds || 0);
  const startedAt = Date.now();
  let sawDown = false;
  const poll = async () => {
    if (Date.now() - startedAt > 25000) {
      window.location.reload();
      return;
    }
    try {
      const res = await fetch("/api/status", { cache: "no-store", credentials: "same-origin" });
      if (res.status === 401 || res.status === 403) {
        window.location.reload();
        return;
      }
      if (res.ok) {
        const data = await res.json().catch(() => null);
        const uptime = Number(data?.metrics?.uptime_seconds ?? NaN);
        if (sawDown || (Number.isFinite(uptime) && (uptime < initialUptime || (initialUptime <= 0 && uptime < 15)))) {
          window.location.reload();
          return;
        }
      }
    } catch (_err) {
      sawDown = true;
    }
    window.setTimeout(poll, 1000);
  };
  window.setTimeout(poll, 1500);
}

document.querySelectorAll("[data-service-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.serviceAction;
    closeServiceMenu();
    if (action === "stop" && !window.confirm("确认停止 Telegram 服务？停止期间所有模块将暂停运行。")) return;
    if (action === "restart" && !window.confirm("确认重启服务进程？服务将短暂中断数秒。")) return;
    try {
      await postJson(`/api/service/${action}`, {});
      if (action === "restart") {
        showToast("已触发重启，服务恢复后将自动刷新页面…", "success");
        waitForRestartAndReload();
        return;
      }
      showToast(action === "stop" ? "已发送停止指令" : "已发送启动指令", "success");
      await refreshAll();
    } catch (error) {
      showToast(`服务操作失败：${error.message}`, "error");
    }
  });
});
document.getElementById("serviceMenuToggle").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleServiceMenu();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest("#serviceMenu")) closeServiceMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (window.uiStudio?.handleEscape?.()) return;
    closeServiceMenu();
    closeCommandPalette();
    closeMobileNav();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    toggleCommandPalette();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    const activeView = document.querySelector(".view.active");
    const saveId = activeView?.id === "moduleRedPacket" ? "saveRedPacketTemplates" : activeView?.dataset?.saveBtn;
    const saveBtn = saveId ? document.getElementById(saveId) : null;
    if (saveBtn && !saveBtn.disabled) {
      event.preventDefault();
      saveBtn.click();
    }
  }
});

document.getElementById("refreshLogs").addEventListener("click", refreshLogs);
document.getElementById("autoRefreshLogs").addEventListener("change", (event) => {
  state.logAutoRefresh = event.target.checked;
  if (state.logAutoRefresh) {
    state.logSourceTab = "live";
    state.logsViewingFile = false;
    state.activeLogFile = "";
    syncLogToolbarUI();
  }
  updateLogRefreshState();
  scheduleLogRefreshLoop();
  if (state.logAutoRefresh) void refreshLogs();
});
const logRefreshIntervalInput = document.getElementById("logRefreshInterval");
if (logRefreshIntervalInput) {
  logRefreshIntervalInput.value = formatRefreshInterval(state.logRefreshIntervalSeconds);
  logRefreshIntervalInput.addEventListener("input", (event) => handleLogRefreshIntervalChange(event, false));
  logRefreshIntervalInput.addEventListener("change", (event) => handleLogRefreshIntervalChange(event, true));
}
document.getElementById("loadGroups").addEventListener("click", loadGroups);
bindSaveButton("saveGroups", saveGroups, "监听群组已保存并实时生效");
bindSaveButton("saveAiServicesConfig", saveAiServicesConfig, "AI 服务配置已保存");
bindSaveButton("saveAiReplyConfig", saveAiReplyConfig, "AI 自动回复配置已保存");
bindSaveButton("saveUserProfileConfig", saveUserProfileConfig, "群友画像配置已保存");
bindSaveButton("saveAiImageConfig", saveAiImageConfig, "AI 生图配置已保存");
bindSaveButton("saveAiDecryptConfig", saveAiDecryptConfig, "AI 解密配置已保存");
bindSaveButton("saveSendRedPacketConfig", saveSendRedPacketConfig, "发红包配置已保存");
bindSaveButton("saveGifConfig", saveGifConfig, "GIF 配置已保存");
bindSaveButton("saveAutoForwardConfig", saveAutoForwardConfig, "自动转发配置已保存");
bindSaveButton("saveMagnetImportConfig", saveMagnetImportConfig, "磁力数据导入配置已保存");
bindSaveButton("saveRexWidgetSyncConfig", saveRexWidgetSyncConfig, "Rex 模块同步配置已保存");
bindSaveButton("saveWordCloudConfig", saveWordCloudConfig, "词云配置已保存");
bindSaveButton("saveQuoteConfig", saveQuoteConfig, "语录配置已保存");
bindSaveButton("saveChatGamesConfig", saveChatGamesConfig, "小游戏配置已保存");
document.getElementById("loadCheckinTargets").addEventListener("click", loadCheckinTargets);
document.getElementById("addCheckinTask").addEventListener("click", addCheckinTask);
document.getElementById("addDecryptTemplate").addEventListener("click", addDecryptTemplate);
document.getElementById("addSendRedPacketTemplate").addEventListener("click", addSendRedPacketTemplate);
bindSaveButton("saveCheckinConfig", saveCheckinConfig, "自动签到配置已保存并实时生效");
document.getElementById("refreshUsage").addEventListener("click", refreshAiUsage);
document.getElementById("usageRange").addEventListener("change", refreshAiUsage);
document.querySelectorAll("[data-chart-window]").forEach((button) => {
  button.addEventListener("click", () => {
    state.chartWindow = button.dataset.chartWindow || "15m";
    document.querySelectorAll("[data-chart-window]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    drawCharts();
  });
});
renderStaticIcons();
initSecretInputs();
initThemeControls();

function currentTheme() {
  const attr = document.documentElement.dataset.theme;
  if (attr === "dark" || attr === "light") return attr;
  return "dark";
}

function applyTheme(theme, persist = false) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalized;
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch (_error) {}
    window.uiStudio?.onThemeChanged?.(normalized);
  }
  const metaTheme = document.querySelector('meta[name="theme-color"]');
  if (metaTheme) metaTheme.setAttribute("content", normalized === "dark" ? "#110e0d" : "#f7f5f5");
  const button = document.getElementById("themeToggle");
  if (button) {
    const icon = button.querySelector(".theme-icon");
    if (icon) {
      icon.dataset.icon = normalized === "dark" ? "sun" : "moon";
      icon.innerHTML = iconSvg(icon.dataset.icon);
    }
    const label = normalized === "dark" ? "切换到浅色主题" : "切换到深色主题";
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  }
  drawCharts();
  if (state.lastUsageData) renderUsage(state.lastUsageData);
}

function initThemeControls() {
  applyTheme(currentTheme(), false);
  const button = document.getElementById("themeToggle");
  if (button) {
    button.addEventListener("click", () => {
      applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
    });
  }
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (media?.addEventListener) {
    media.addEventListener("change", (event) => {
      try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === "dark" || saved === "light") return;
      } catch (_error) {}
      applyTheme(event.matches ? "dark" : "light", false);
    });
  }
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (resizeTimer) window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      drawCharts();
      if (state.lastUsageData) renderUsage(state.lastUsageData);
    }, 120);
  });
}

function showView(viewId) {
  const view = document.getElementById(viewId);
  if (!view) return;

  state.currentView = viewId;
  closeMobileNav();
  prepareView(viewId);
  document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
  view.classList.add("active");

  document.querySelectorAll(".nav-item, .sub-nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });
  document.getElementById("topbarLogsBtn")?.classList.toggle("active", viewId === "logs");
  document.querySelectorAll(".nav-group").forEach((group) => {
    const ownsView = Boolean(group.querySelector(`[data-view="${viewId}"]`));
    group.classList.toggle("active", ownsView);
    if (ownsView) setGroupExpanded(group, true);
  });

  const title = titles[viewId] || titles.dashboard;
  document.getElementById("pageTitle").textContent = title[0];
  document.getElementById("pageSubtitle").textContent = title[1];
  const pageIcon = document.getElementById("pageIcon");
  if (pageIcon) pageIcon.innerHTML = iconSvg(viewIconMap[viewId] || "dashboard");

  const badge = document.getElementById("pageCategoryBadge");
  if (badge) {
    const modId = view.dataset.moduleView;
    const catKey = modId ? MODULE_CATEGORY_KEYS[modId] : null;
    if (catKey && CATEGORY_LABELS[catKey]) {
      badge.textContent = CATEGORY_LABELS[catKey];
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  syncDirtySaveBar();
  window.scrollTo({ top: 0, behavior: "instant" });
  window.uiStudio?.onViewShown?.(viewId);
  if (viewId === "dashboard") {
    window.requestAnimationFrame(() => drawCharts());
  } else if (viewId === "aiUsage" && state.lastUsageData) {
    window.requestAnimationFrame(() => renderUsage(state.lastUsageData));
  }
}

function toggleServiceMenu() {
  const menu = document.getElementById("serviceMenu");
  const expanded = !menu.classList.contains("open");
  menu.classList.toggle("open", expanded);
  document.getElementById("serviceMenuToggle").setAttribute("aria-expanded", String(expanded));
}

function closeServiceMenu() {
  const menu = document.getElementById("serviceMenu");
  if (!menu) return;
  menu.classList.remove("open");
  document.getElementById("serviceMenuToggle")?.setAttribute("aria-expanded", "false");
}

function setGroupExpanded(group, expanded) {
  group.classList.toggle("expanded", expanded);
  const chevron = group.querySelector(".chevron");
  if (chevron) {
    chevron.dataset.icon = expanded ? "chevronUp" : "chevronDown";
    chevron.innerHTML = iconSvg(chevron.dataset.icon);
  }
}

function renderStaticIcons() {
  document.querySelectorAll("[data-icon]").forEach((target) => {
    target.innerHTML = iconSvg(target.dataset.icon);
  });
}

function moduleIconKey(moduleId) {
  return {
    red_packet: "red_packet",
    send_red_packet: "send_red_packet",
    ai_reply: "ai_reply",
    user_profile: "user_profile",
    ai_image: "ai_image",
    ai_decrypt: "ai_decrypt",
    gif: "gif",
    word_cloud: "word_cloud",
    checkin: "checkin",
    auto_forward: "auto_forward",
    magnet_import: "magnet_import",
    rex_widget_sync: "rex_widget_sync",
    quote: "quote",
    chat_games: "chat_games",
  }[moduleId] || "modules";
}

function iconSvg(name) {
  const body = ICONS[name] || ICONS.modules;
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>`;
}

function prepareView(viewId) {
  if (viewId === "moduleRedPacket") {
    const module = findModule("red_packet");
    if (module) showRedPacketDetail(module);
  }
  if (viewId === "moduleSendRedPacket") {
    const module = findModule("send_red_packet");
    if (module) fillSendRedPacketSettings(module.config || {});
  }
  if (viewId === "moduleGif") {
    const module = findModule("gif");
    if (module) fillGifSettings(module.config || {});
  }
  if (viewId === "moduleWordCloud") {
    const module = findModule("word_cloud");
    if (module) fillWordCloudSettings(module);
  }
  if (viewId === "moduleAiReply" || viewId === "moduleAiImage" || viewId === "aiServices") {
    void refreshAi();
  }
  if (viewId === "moduleUserProfile") {
    const module = findModule("user_profile");
    if (module) fillUserProfileSettings(module);
  }
  if (viewId === "moduleAiDecrypt") {
    const module = findModule("ai_decrypt");
    if (module) fillDecryptSettings(module.config || {});
  }
  if (viewId === "moduleCheckin") {
    const module = findModule("checkin");
    if (module) showCheckinSettings(module);
  }
  if (viewId === "moduleAutoForward") {
    const module = findModule("auto_forward");
    if (module) fillAutoForwardSettings(module);
  }
  if (viewId === "moduleMagnetImport") {
    const module = findModule("magnet_import");
    if (module) fillMagnetImportSettings(module);
  }
  if (viewId === "moduleRexWidgetSync") {
    const module = findModule("rex_widget_sync");
    if (module) fillRexWidgetSyncSettings(module);
  }
  if (viewId === "moduleQuote") {
    const module = findModule("quote");
    if (module) fillQuoteSettings(module);
  }
  if (viewId === "moduleChatGames") {
    const module = findModule("chat_games");
    if (module) fillChatGamesSettings(module);
  }
  if (viewId === "logs") {
    syncLogToolbarUI();
    if (state.logSourceTab === "archive") {
      void refreshLogFiles();
    } else {
      state.logsViewingFile = false;
      updateLogRefreshState();
      void refreshLogs();
    }
  }
  if (viewId === "aiUsage") refreshAiUsage();
  window.uiStudio?.onViewDataRendered?.(viewId);
}

function bindSaveButton(id, handler, successMessage) {
  const button = document.getElementById(id);
  if (!button) return;
  button.addEventListener("click", () => {
    void withSaveFeedback(button, handler, successMessage).catch(() => {});
  });
}

async function withSaveFeedback(button, handler, successMessage = "已保存") {
  const originalText = button.textContent;
  button.disabled = true;
  button.classList.add("saving");
  button.textContent = "保存中...";
  try {
    const result = await handler();
    if (result && typeof result === "object" && result.ok === false) {
      throw new Error(result.error || "保存失败");
    }
    const ownerView = button.closest(".view")?.id || state.currentView;
    if (ownerView) clearViewDirty(ownerView);
    window.uiStudio?.onSaveSucceeded?.(ownerView);
    showToast(successMessage, "success");
    return result;
  } catch (error) {
    showToast(`保存失败：${error.message}`, "error");
    throw error;
  } finally {
    button.disabled = false;
    button.classList.remove("saving");
    button.textContent = originalText;
  }
}

function showToast(message, type = "success") {
  const host = document.getElementById("toastHost");
  if (!host) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type === "error" ? "error" : "success"}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  host.appendChild(toast);
  window.setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-6px)";
    window.setTimeout(() => toast.remove(), 180);
  }, type === "error" ? 5200 : 2600);
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshModules(), refreshAi(), refreshAiUsage(), refreshLogs(), refreshSettings()]);
}

async function refreshStatus() {
  const data = await getJson("/api/status");
  state.status = data;

  document.getElementById("serviceState").textContent = data.service.state;
  document.getElementById("serviceState").className = `status-pill ${data.service.state}`;

  ingestMetricHistory(data);

  renderDashboardKpis(data);
  renderDevice(data);
  renderHardware(data);
  renderStats(data);
  drawCharts();
}

function renderDashboardKpis(data) {
  const tg = data.telegram || {};
  const metrics = data.metrics || {};
  const project = data.project || {};
  const groupCount = Array.isArray(tg.monitored_groups) ? tg.monitored_groups.length : 0;

  const tgBadge = document.getElementById("kpiTgBadge");
  const tgValue = document.getElementById("kpiTgValue");
  const tgSub = document.getElementById("kpiTgSub");
  const connected = Boolean(tg.connected);
  if (tgBadge) {
    tgBadge.textContent = connected ? "在线" : tg.enabled === false ? "已禁用" : "离线";
    tgBadge.className = `mini-badge ${connected ? "ok" : tg.enabled === false ? "warn" : "err"}`;
  }
  if (tgValue) tgValue.textContent = connected ? "已连接" : "未连接";
  if (tgSub) {
    const parts = [
      groupCount ? `监听 ${groupCount} 个群组` : "监听全部可见群",
      metrics.pid ? `PID ${metrics.pid}` : "",
    ].filter(Boolean);
    tgSub.textContent = tg.last_error ? `异常：${tg.last_error}` : parts.join(" · ");
  }

  const sidebarDot = document.getElementById("sidebarTgDot");
  const sidebarState = document.getElementById("sidebarTgState");
  const topbarVersion = document.getElementById("topbarVersion");
  if (sidebarDot) sidebarDot.className = `pulse-dot ${connected ? "online" : "offline"}`;
  if (sidebarState) sidebarState.textContent = connected ? "Telegram 已连接" : "Telegram 未连接";
  if (topbarVersion) {
    const versionText = project.version ? `v${project.version}` : "v0.1.0";
    topbarVersion.textContent = versionText;
    topbarVersion.title = `${project.name || "Telebot"} ${versionText}`;
  }

  const msgValue = document.getElementById("kpiMsgValue");
  const msgSub = document.getElementById("kpiMsgSub");
  const failBadge = document.getElementById("kpiFailBadge");
  const failures = Number(metrics.failures || 0);
  if (msgValue) msgValue.textContent = formatNumber(metrics.messages_handled || 0);
  if (msgSub) msgSub.textContent = `捕获 ${formatNumber(metrics.messages_seen || 0)} 条 · 运行 ${formatDuration(metrics.uptime_seconds || 0)}`;
  if (failBadge) {
    failBadge.textContent = `${failures} 异常`;
    failBadge.className = `mini-badge ${failures > 0 ? "err" : "ok"}`;
  }

  if (Array.isArray(data.modules) && data.modules.length) {
    updateModulesOverview(data.modules);
  }
}

function renderDevice(data) {
  const device = data.system.device;
  const list = document.getElementById("deviceInfo");
  list.innerHTML = "";
  addKv(list, "主机名", device.hostname);
  addKv(list, "系统平台", device.system_platform);
  addKv(list, "运行时间", formatDuration(device.uptime_seconds));
  addKv(list, "操作系统", device.os);
  addKv(list, "架构", device.architecture);
}

function renderHardware(data) {
  const hardware = data.system.hardware;
  const list = document.getElementById("hardwareInfo");
  list.innerHTML = "";
  addKv(list, "硬件信息", hardware.processor);
  addKv(list, "核心数", `${hardware.cores} 核心`);
  addKv(list, "内存", formatBytes(hardware.memory_total_bytes));
  addKv(list, "硬盘容量", formatBytes(hardware.disk_total_bytes));
  addKv(list, "硬盘使用率", `${hardware.disk_percent}%`);
  const pct = Math.min(Number(hardware.disk_percent || 0), 100);
  document.getElementById("diskMeter").style.width = `${pct}%`;
  const diskVal = document.getElementById("diskMeterValue");
  if (diskVal) diskVal.textContent = `${pct.toFixed(1).replace(/\.0$/, "")}%`;
}

function renderStats(data) {
  const stats = data.system.stats;
  const latest = state.metricHistory.at(-1) || {};
  const list = document.getElementById("statsInfo");
  list.innerHTML = "";
  addKv(list, "系统运行时间", formatDuration(data.metrics.uptime_seconds));
  addKv(list, "总上传流量", formatBytes(stats.upload_bytes));
  addKv(list, "总下载流量", formatBytes(stats.download_bytes));
  addKv(list, "当前上传速度", formatBytesPerSecond(latest.uploadRate || 0));
  addKv(list, "当前下载速度", formatBytesPerSecond(latest.downloadRate || 0));
  addKv(list, "CPU 使用率", `${Number(data.metrics.cpu_percent || 0).toFixed(1)}%`);
  addKv(list, "内存使用率", `${Number(stats.memory_percent || 0).toFixed(1)}%`);

  document.getElementById("cpuLegend").textContent = `${Number(data.metrics.cpu_percent || 0).toFixed(1)}%`;
  document.getElementById("memoryLegend").textContent = `${Number(stats.memory_percent || 0).toFixed(1)}%`;
  document.getElementById("downloadLegend").textContent = formatBytesPerSecond(latest.downloadRate || 0);
  document.getElementById("uploadLegend").textContent = formatBytesPerSecond(latest.uploadRate || 0);
}

async function refreshModules() {
  const data = await getJson("/api/modules");
  state.modules = data.modules || [];
  updateModulesOverview(state.modules);
  renderModuleCards();
}

function updateModulesOverview(modules) {
  const total = modules.length;
  const enabledCount = modules.filter((item) => item.enabled).length;

  const kpiVal = document.getElementById("kpiModulesValue");
  const kpiBar = document.getElementById("kpiModulesBar");
  const kpiSub = document.getElementById("kpiModulesSub");
  if (kpiVal) kpiVal.textContent = `${enabledCount} / ${total}`;
  if (kpiBar) kpiBar.style.width = `${total ? Math.round((enabledCount / total) * 100) : 0}%`;
  if (kpiSub) kpiSub.textContent = `${enabledCount} 个运行中 · ${Math.max(total - enabledCount, 0)} 个已停用`;

  const byId = new Map(modules.map((item) => [item.id, item]));
  document.querySelectorAll("[data-module-nav]").forEach((navItem) => {
    const mod = byId.get(navItem.dataset.moduleNav);
    navItem.classList.toggle("is-enabled", Boolean(mod?.enabled));
  });

  document.querySelectorAll("[data-module-toggle]").forEach((input) => {
    const mod = byId.get(input.dataset.moduleToggle);
    if (mod) input.checked = Boolean(mod.enabled);
  });

  const bannerStateMap = {
    send_red_packet: "sendRedPacketModuleState",
    ai_reply: "aiReplyModuleState",
    ai_image: "aiImageModuleState",
    ai_decrypt: "aiDecryptModuleState",
    gif: "gifModuleState",
  };
  Object.entries(bannerStateMap).forEach(([moduleId, elId]) => {
    const el = document.getElementById(elId);
    const mod = byId.get(moduleId);
    if (el && mod) {
      el.textContent = mod.enabled ? "模块已启用" : "模块未启用";
      el.className = `tag ${mod.enabled ? "enabled" : "disabled"}`;
    }
  });

  const quickHost = document.getElementById("dashboardQuickModules");
  if (quickHost) {
    quickHost.innerHTML = "";
    modules.forEach((mod) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `quick-mod-chip ${mod.enabled ? "enabled" : ""}`;
      chip.innerHTML = `
        <span class="qm-ico">${iconSvg(moduleIconKey(mod.id))}</span>
        <span class="qm-meta">
          <strong>${escapeHtml(mod.name)}</strong>
          <small>${mod.enabled ? "运行中" : "已停用"}</small>
        </span>
      `;
      chip.addEventListener("click", () => openModuleConfig(mod));
      quickHost.appendChild(chip);
    });
  }
  window.uiStudio?.onModulesUpdated?.(modules);
}

function renderModuleCards() {
  const container = document.getElementById("moduleCards");
  if (!container) return;
  container.innerHTML = "";

  const query = state.moduleSearchQuery.trim().toLowerCase();
  const filtered = state.modules.filter((module) => {
    const catKey = MODULE_CATEGORY_KEYS[module.id] || "media";
    if (state.moduleCategoryFilter !== "all" && catKey !== state.moduleCategoryFilter) return false;
    if (state.moduleStatusFilter === "enabled" && !module.enabled) return false;
    if (state.moduleStatusFilter === "disabled" && module.enabled) return false;
    if (query) {
      const haystack = `${module.name} ${module.id} ${module.description || ""} ${module.category || ""}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state">当前筛选条件下没有匹配的模块。</div>';
    return;
  }

  filtered.forEach((module) => {
    const card = document.createElement("article");
    card.className = `module-card ${module.enabled ? "is-enabled" : ""}`;
    card.tabIndex = 0;
    card.role = "button";
    card.dataset.moduleId = module.id;
    const catLabel = CATEGORY_LABELS[MODULE_CATEGORY_KEYS[module.id]] || module.category || "";
    card.innerHTML = `
      <div class="module-card-head">
        <div class="module-title">
          <span class="module-icon" data-module-icon="${escapeAttr(module.id)}">${iconSvg(moduleIconKey(module.id))}</span>
          <h3>${escapeHtml(module.name)}</h3>
        </div>
        <label class="switch module-switch" title="${module.enabled ? "点击禁用模块" : "点击启用模块"}">
          <input type="checkbox" ${module.enabled ? "checked" : ""} aria-label="${escapeAttr(module.name)} 开关">
          <span></span>
        </label>
      </div>
      <p>${escapeHtml(module.description)}</p>
      <div class="module-card-foot">
        <div class="tag-row">
          <span class="tag ${module.enabled ? "enabled" : "disabled"}">${module.enabled ? "已启用" : "未启用"}</span>
          <span class="tag">${escapeHtml(catLabel || module.category)}</span>
        </div>
        <span class="module-open-hint">配置 →</span>
      </div>
    `;
    card.addEventListener("click", () => openModuleConfig(module));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openModuleConfig(module);
      }
    });
    const switchControl = card.querySelector(".module-switch");
    const switchInput = switchControl.querySelector("input");
    switchControl.addEventListener("click", (event) => event.stopPropagation());
    switchInput.addEventListener("change", async (event) => {
      event.stopPropagation();
      const targetChecked = event.target.checked;
      event.target.disabled = true;
      try {
        await toggleModuleEnabled(module.id, targetChecked);
      } catch (error) {
        event.target.checked = !targetChecked;
        showToast(`切换模块状态失败：${error.message}`, "error");
      } finally {
        event.target.disabled = false;
      }
    });
    container.appendChild(card);
  });
}

function findModule(moduleId) {
  return state.modules.find((module) => module.id === moduleId);
}

function openModuleConfig(module) {
  const viewId = moduleViewMap[module.id];
  if (!viewId) return;
  showView(viewId);
}

async function toggleModuleEnabled(moduleId, enabled) {
  const result = await putJson(`/api/modules/${moduleId}`, { enabled });
  const index = state.modules.findIndex((module) => module.id === moduleId);
  if (index >= 0) state.modules[index] = result.module;
  await refreshModules();
  if (moduleId === "red_packet" && document.getElementById("moduleRedPacket").classList.contains("active")) {
    showRedPacketDetail(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "send_red_packet" && document.getElementById("moduleSendRedPacket").classList.contains("active")) {
    fillSendRedPacketSettings(result.module.config || {});
    document.getElementById("sendRedPacketSaveState").textContent = enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效";
  }
  if (moduleId === "ai_reply" || moduleId === "ai_image") {
    await refreshAi();
  }
  if (moduleId === "user_profile" && document.getElementById("moduleUserProfile").classList.contains("active")) {
    fillUserProfileSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "gif" && document.getElementById("moduleGif").classList.contains("active")) {
    fillGifSettings(result.module.config || {});
    document.getElementById("gifSaveState").textContent = enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效";
  }
  if (moduleId === "ai_decrypt" && document.getElementById("moduleAiDecrypt").classList.contains("active")) {
    fillDecryptSettings(result.module.config || {});
    document.getElementById("decryptSaveState").textContent = enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效";
  }
  if (moduleId === "checkin" && document.getElementById("moduleCheckin").classList.contains("active")) {
    showCheckinSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "auto_forward" && document.getElementById("moduleAutoForward").classList.contains("active")) {
    fillAutoForwardSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "magnet_import" && document.getElementById("moduleMagnetImport").classList.contains("active")) {
    fillMagnetImportSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "rex_widget_sync" && document.getElementById("moduleRexWidgetSync").classList.contains("active")) {
    fillRexWidgetSyncSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "word_cloud" && document.getElementById("moduleWordCloud").classList.contains("active")) {
    fillWordCloudSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "quote" && document.getElementById("moduleQuote").classList.contains("active")) {
    fillQuoteSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
  if (moduleId === "chat_games" && document.getElementById("moduleChatGames").classList.contains("active")) {
    fillChatGamesSettings(result.module, enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  }
}

function showRedPacketDetail(module, notice = "") {
  const templates = Array.isArray(module.config?.templates) ? module.config.templates : [];
  const sendDelayMs = Number(module.config?.send_delay_ms || 0);
  const preClickMessages = Array.isArray(module.config?.pre_click_messages) ? module.config.pre_click_messages : [];
  const detail = document.getElementById("moduleRedPacketConfig");
  detail.innerHTML = `
    <div class="module-banner">
      <div class="module-banner-meta">
        <div class="banner-tags red-packet-summary">
          <span class="tag ${module.enabled ? "enabled" : "disabled"}">${module.enabled ? "模块已启用" : "模块未启用"}</span>
          <span class="tag">模板 ${templates.length} 个</span>
          <span class="tag">图片识别已停用</span>
          <span class="tag">ID 去重 48 小时</span>
          <span id="redPacketSaveState" class="hint">${escapeHtml(notice)}</span>
        </div>
      </div>
      <div class="module-actions">
        <button id="toggleModule" type="button" class="${module.enabled ? "" : "primary"}">${module.enabled ? "禁用" : "启用"}</button>
        <button id="addRedPacketTemplate" type="button">新增模板</button>
        <button id="saveRedPacketTemplates" type="button" class="primary">保存模板</button>
      </div>
    </div>
    <div class="workspace-layout">
      <div class="workspace-main">
        <section class="section-card">
          <div class="section-head">
            <div>
              <h3>发言与延迟策略</h3>
              <p class="hint">按钮模板首次点击不等待；开启“首次抢后自动发言”后：立即点击 → 随机发言 → 可选延迟 → 再次点击。未开启时延迟不生效。</p>
            </div>
          </div>
          <div class="red-packet-settings setting-form form-grid" aria-label="抢红包发送设置">
            <label class="field">
              <span>发送延迟</span>
              <span class="red-packet-delay-control">
                <input id="redPacketSendDelayMs" type="number" min="0" max="60000" step="100" value="${sendDelayMs}" aria-label="发送延迟（毫秒）">
                <small>ms</small>
              </span>
            </label>
            <label class="field wide-field">
              <span>自动发言候选</span>
              <span class="red-packet-message-control">
                <textarea id="redPacketPreClickMessages" rows="4" aria-describedby="redPacketPreClickMessagesHint" placeholder="手气不错&#10;感谢老板">${escapeHtml(preClickMessages.join("\n"))}</textarea>
                <small id="redPacketPreClickMessagesHint" class="hint">每行一条，首次点击后随机发送；开启延迟时，等待后再次点击。消息中的逗号会原样保留。</small>
              </span>
            </label>
          </div>
        </section>
        <section class="section-card">
          <div class="section-head">
            <div>
              <h3>红包与抽奖匹配模板</h3>
              <p class="hint">按模板匹配关键词、结构标记、口令定位或按钮文案，支持独立启停每条模板。</p>
            </div>
          </div>
          <div id="redPacketTemplates" class="template-list"></div>
        </section>
      </div>
      <aside class="workspace-aside">
        <section class="aside-card">
          <h4>执行策略</h4>
          <div class="gif-help">
            <span class="tag">同 ID 48 小时内不重复抢</span>
            <span class="tag">自己发出的红包自动跳过</span>
            <span class="tag">保存模板后实时生效</span>
          </div>
        </section>
      </aside>
    </div>
  `;
  const list = document.getElementById("redPacketTemplates");
  templates.forEach((template) => list.appendChild(redPacketTemplateForm(template)));
  if (!templates.length) {
    list.innerHTML = '<div class="empty-state">还没有模板。点击“新增模板”创建第一个红包或抽奖规则。</div>';
  }
  document.getElementById("toggleModule").addEventListener("click", async () => {
    try {
      const result = await putJson(`/api/modules/${module.id}`, { enabled: !module.enabled });
      await refreshModules();
      showRedPacketDetail(result.module, result.module.enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
    } catch (error) {
      showToast(`切换模块状态失败：${error.message}`, "error");
    }
  });
  document.getElementById("addRedPacketTemplate").addEventListener("click", () => {
    const empty = list.querySelector(".empty-state");
    if (empty) empty.remove();
    const card = redPacketTemplateForm(newRedPacketTemplate());
    list.appendChild(card);
    markViewDirty("moduleRedPacket");
    window.uiStudio?.onTemplateAdded?.("moduleRedPacket", card);
  });
  const saveTemplatesButton = document.getElementById("saveRedPacketTemplates");
  saveTemplatesButton.addEventListener("click", () => {
    void withSaveFeedback(saveTemplatesButton, async () => {
      const templates = collectRedPacketTemplates();
      const messageInput = document.getElementById("redPacketPreClickMessages");
      const preClickMessages = splitRows(messageInput.value);
      if (templates.some((template) => template.send_message_before_click) && !preClickMessages.length) {
        messageInput.focus();
        throw new Error("已开启“首次抢后自动发言”，请至少配置一条首次抢后发言候选");
      }
      const payload = {
        config: {
          templates,
          send_delay_ms: Number(document.getElementById("redPacketSendDelayMs").value || 0),
          pre_click_messages: preClickMessages,
        },
      };
      const result = await putJson(`/api/modules/${module.id}`, payload);
      showRedPacketDetail(result.module, "已保存并实时生效");
      await refreshModules();
      return result;
    }, "红包模板已保存并实时生效").catch(() => {});
  });
  window.uiStudio?.onViewDataRendered?.("moduleRedPacket");
}

function newRedPacketTemplate() {
  return {
    id: `template_${Date.now()}`,
    name: "",
    enabled: true,
    trigger_keywords: ["红包"],
    id_markers: [],
    passphrase_markers: [],
    button_texts: [],
    send_message_before_click: false,
    delay_before_click: true,
  };
}

function redPacketTemplateForm(template) {
  const card = document.createElement("section");
  card.className = "template-card";
  card.dataset.templateId = template.id || `template_${Date.now()}`;
  card.innerHTML = `
    <div class="template-head red-packet-template-head">
      <div class="red-packet-template-options">
        <label class="inline-check"><input data-field="enabled" type="checkbox" ${template.enabled === false ? "" : "checked"}> 启用</label>
        <label class="inline-check"><input data-field="send_message_before_click" type="checkbox" ${template.send_message_before_click === true ? "checked" : ""}> 首次抢后自动发言</label>
        <label class="inline-check" title="仅在开启首次抢后自动发言时生效"><input data-field="delay_before_click" type="checkbox" ${template.delay_before_click !== false ? "checked" : ""}> 发言后延迟再抢</label>
      </div>
      <button class="danger" data-action="remove-template">删除</button>
    </div>
    <div class="template-fields">
      <label><span>模板名称</span><input data-field="name" type="text" value="${escapeAttr(template.name || "")}" placeholder="红包口令"></label>
      <label><span>触发关键词</span><textarea data-field="trigger_keywords" placeholder="红包&#10;抽奖">${escapeHtml((template.trigger_keywords || []).join("\n"))}</textarea></label>
      <label><span>ID/结构标记</span><textarea data-field="id_markers" placeholder="红包ID:&#10;【幸运红包】">${escapeHtml((template.id_markers || []).join("\n"))}</textarea></label>
      <label><span>口令定位标记</span><textarea data-field="passphrase_markers" placeholder="领取密令:&#10;发送下方口令领取：&#10;参与关键词：">${escapeHtml((template.passphrase_markers || []).join("\n"))}</textarea></label>
      <label><span>按钮文案</span><textarea data-field="button_texts" placeholder="抢红包&#10;立即领取">${escapeHtml((template.button_texts || []).join("\n"))}</textarea></label>
    </div>
  `;
  card.querySelector('[data-action="remove-template"]').addEventListener("click", () => {
    card.remove();
    const list = document.getElementById("redPacketTemplates");
    if (list && !list.querySelector(".template-card")) {
      list.innerHTML = '<div class="empty-state">还没有模板。点击“新增模板”创建第一个红包或抽奖规则。</div>';
    }
  });
  return card;
}

function collectRedPacketTemplates() {
  return Array.from(document.querySelectorAll("#redPacketTemplates .template-card")).map((card) => ({
    id: card.dataset.templateId,
    name: card.querySelector('[data-field="name"]').value.trim(),
    enabled: card.querySelector('[data-field="enabled"]').checked,
    send_message_before_click: card.querySelector('[data-field="send_message_before_click"]').checked,
    delay_before_click: card.querySelector('[data-field="delay_before_click"]').checked,
    trigger_keywords: splitLines(card.querySelector('[data-field="trigger_keywords"]').value),
    id_markers: splitLines(card.querySelector('[data-field="id_markers"]').value),
    passphrase_markers: splitLines(card.querySelector('[data-field="passphrase_markers"]').value),
    button_texts: splitLines(card.querySelector('[data-field="button_texts"]').value),
    passphrase: "",
  }));
}

function splitLines(value) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitRows(value) {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function fillSendRedPacketSettings(settings) {
  const form = document.getElementById("sendRedPacketSettingsForm");
  if (!form) return;
  setFormValue(form, "id_length", settings.id_length || 6);
  setFormValue(form, "max_active_packets", settings.max_active_packets || 20);
  setFormValue(form, "min_packet_amount", settings.min_packet_amount || 2);
  setFormValue(form, "strict_min_packet_amount", settings.strict_min_packet_amount || 101);
  setFormLines(form, "strict_min_packet_group_ids", settings.strict_min_packet_group_ids || []);
  setFormValue(form, "state_store", settings.state_store || "runtime/data/send_red_packet_state.json");
  const list = document.getElementById("sendRedPacketTemplates");
  const templates = Array.isArray(settings.templates) ? settings.templates : [];
  list.innerHTML = "";
  templates.forEach((template) => list.appendChild(sendRedPacketTemplateForm(template)));
  if (!templates.length) {
    list.innerHTML = '<div class="empty-state">还没有发红包模板。点击“新增模板”创建第一种红包玩法。</div>';
  }
  const stateLabel = document.getElementById("sendRedPacketSaveState");
  if (stateLabel) {
    stateLabel.textContent = `当前活跃红包 ${Number(settings.active_packet_count || 0)} 个，模板 ${templates.length} 个。`;
  }
}

function newSendRedPacketTemplate() {
  return {
    id: `send_template_${Date.now()}`,
    name: "拼手气红包",
    type: "lucky_text",
    enabled: true,
    command_prefixes: ["红包", "/红包"],
    max_packet_count: 100,
  };
}

function addSendRedPacketTemplate() {
  const list = document.getElementById("sendRedPacketTemplates");
  const empty = list.querySelector(".empty-state");
  if (empty) empty.remove();
  const card = sendRedPacketTemplateForm(newSendRedPacketTemplate());
  list.appendChild(card);
  markViewDirty("moduleSendRedPacket");
  window.uiStudio?.onTemplateAdded?.("moduleSendRedPacket", card);
}

function sendRedPacketTemplateForm(template) {
  const card = document.createElement("section");
  card.className = "template-card";
  card.dataset.templateId = template.id || `send_template_${Date.now()}`;
  const templateType = template.type || "lucky_text";
  const commandFormat = templateType === "math_quiz" ? "/math 6666" : "红包 10000 10 哈哈哈";
  card.innerHTML = `
    <div class="template-head">
      <label class="inline-check"><input data-field="enabled" type="checkbox" ${template.enabled === false ? "" : "checked"}> 启用</label>
      <button class="danger" data-action="remove-send-red-packet-template">删除</button>
    </div>
    <div class="template-fields">
      <label><span>模板名称</span><input data-field="name" type="text" value="${escapeAttr(template.name || "")}" placeholder="拼手气红包"></label>
      <label><span>模板类型</span><select data-field="type"><option value="lucky_text">拼手气口令红包</option></select></label>
      <label><span>创建指令</span><textarea data-field="command_prefixes" rows="3" placeholder="红包&#10;/红包">${escapeHtml((template.command_prefixes || []).join("\n"))}</textarea></label>
      <label><span>单个红包最大数量</span><input data-field="max_packet_count" type="number" min="1" max="1000" step="1" value="${Number(template.max_packet_count || 100)}"></label>
      <label class="wide-field"><span>指令格式</span><input type="text" value="红包 10000 10 哈哈哈" disabled></label>
    </div>
  `;
  const typeSelect = card.querySelector('[data-field="type"]');
  if (typeSelect && !typeSelect.querySelector('option[value="math_quiz"]')) {
    typeSelect.append(new Option("趣味算术题", "math_quiz"));
  }
  if (typeSelect) typeSelect.value = templateType;
  const commandFormatInput = card.querySelector(".wide-field input");
  if (commandFormatInput) commandFormatInput.value = commandFormat;
  if (typeSelect) {
    typeSelect.addEventListener("change", () => {
      const input = card.querySelector(".wide-field input");
      if (input) input.value = typeSelect.value === "math_quiz" ? "/math 6666" : "红包 10000 10 哈哈哈";
    });
  }
  card.querySelector('[data-action="remove-send-red-packet-template"]').addEventListener("click", () => {
    card.remove();
    const list = document.getElementById("sendRedPacketTemplates");
    if (list && !list.querySelector(".template-card")) {
      list.innerHTML = '<div class="empty-state">还没有发红包模板。点击“新增模板”创建第一种红包玩法。</div>';
    }
  });
  return card;
}

function collectSendRedPacketTemplates() {
  return Array.from(document.querySelectorAll("#sendRedPacketTemplates .template-card")).map((card) => ({
    id: card.dataset.templateId,
    name: card.querySelector('[data-field="name"]').value.trim(),
    type: card.querySelector('[data-field="type"]').value,
    enabled: card.querySelector('[data-field="enabled"]').checked,
    command_prefixes: splitLines(card.querySelector('[data-field="command_prefixes"]').value),
    max_packet_count: Number(card.querySelector('[data-field="max_packet_count"]').value || 100),
  }));
}

function collectSendRedPacketSettings() {
  const form = document.getElementById("sendRedPacketSettingsForm");
  return {
    templates: collectSendRedPacketTemplates(),
    id_length: Number(form.elements.id_length.value || 6),
    max_active_packets: Number(form.elements.max_active_packets.value || 20),
    min_packet_amount: Number(form.elements.min_packet_amount.value || 2),
    strict_min_packet_amount: Number(form.elements.strict_min_packet_amount.value || 101),
    strict_min_packet_group_ids: splitLines(form.elements.strict_min_packet_group_ids.value),
    state_store: form.elements.state_store.value.trim() || "runtime/data/send_red_packet_state.json",
  };
}

async function saveSendRedPacketConfig() {
  const result = await putJson("/api/modules/send_red_packet", { config: collectSendRedPacketSettings() });
  const index = state.modules.findIndex((module) => module.id === "send_red_packet");
  if (index >= 0) state.modules[index] = result.module;
  document.getElementById("sendRedPacketSaveState").textContent = result.ok ? "已保存，后续发红包会使用新配置。" : "保存失败";
  fillSendRedPacketSettings(result.module.config || {});
  await refreshModules();
  return result;
}

async function refreshAi() {
  const data = await getJson("/api/ai");
  state.ai = data;
  fillProviderForm("reply_provider", data.providers.reply);
  fillProviderForm("image_provider", data.providers.image);
  fillReplySettings(data.reply || {});
  fillImageSettings(data.image || {});
  const replyKeyState = document.getElementById("replyKeyState");
  replyKeyState.textContent = data.providers.reply.has_api_key ? "已配置 Key" : "未配置 Key";
  replyKeyState.classList.toggle("configured", Boolean(data.providers.reply.has_api_key));
  const imageKeyState = document.getElementById("imageKeyState");
  imageKeyState.textContent = data.providers.image.has_api_key ? "已配置 Key" : "未配置 Key";
  imageKeyState.classList.toggle("configured", Boolean(data.providers.image.has_api_key));
  window.uiStudio?.onAiUpdated?.(data);
}

function fillProviderForm(providerName, provider) {
  const form = document.querySelector(`.service-form[data-provider="${providerName}"]`);
  form.elements.name.value = provider.name || "";
  form.elements.provider_type.value = normalizeProviderType(providerName, provider.provider_type);
  form.elements.base_url.value = provider.base_url || "";
  form.elements.api_key.value = "";
  resetSecretInput(form.elements.api_key);
  form.elements.model.value = provider.model || "";
}

function normalizeProviderType(providerName, providerType) {
  const normalized = String(providerType || "openai").trim().toLowerCase();
  if (
    providerName === "image_provider"
    && ["xai", "xai-compatible", "xai-imagine", "grok-imagine"].includes(normalized)
  ) {
    return "xai-imagine";
  }
  return normalized;
}

function initSecretInputs() {
  document.querySelectorAll("[data-secret-toggle]").forEach((button) => {
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => {
      const input = button.closest(".secret-input")?.querySelector("[data-secret-input]");
      if (!input) return;
      const visible = input.type === "text";
      input.dataset.pinned = visible ? "false" : "true";
      input.type = visible ? "password" : "text";
      button.textContent = visible ? "显示" : "隐藏";
      button.setAttribute("aria-pressed", String(!visible));
      input.focus();
    });
  });
}

function resetSecretInput(input) {
  if (!input) return;
  input.type = "password";
  input.dataset.pinned = "false";
  const button = input.closest(".secret-input")?.querySelector("[data-secret-toggle]");
  if (button) {
    button.textContent = "显示";
    button.setAttribute("aria-pressed", "false");
  }
}

function collectProviderForm(providerName) {
  const form = document.querySelector(`.service-form[data-provider="${providerName}"]`);
  const data = {
    name: form.elements.name.value.trim(),
    provider_type: form.elements.provider_type.value,
    base_url: form.elements.base_url.value.trim(),
    model: form.elements.model.value.trim(),
  };
  const apiKey = form.elements.api_key.value.trim();
  if (apiKey) data.api_key = apiKey;
  return data;
}

function fillReplySettings(settings) {
  const form = document.getElementById("replySettingsForm");
  if (!form) return;
  setFormValue(form, "system_prompt", settings.system_prompt || "");
  setFormLines(form, "command_prefixes", settings.command_prefixes);
  setFormLines(form, "wake_words", settings.wake_words);
  setFormLines(form, "reply_triggers", settings.reply_triggers);
  setFormValue(form, "context_limit", settings.context_limit ?? 6);
  setFormValue(form, "timeout_seconds", settings.timeout_seconds ?? 180);
  setFormValue(form, "max_tokens", settings.max_tokens ?? 25000);
  setFormValue(form, "temperature", settings.temperature ?? 0.7);
  setFormValue(form, "reasoning_effort", settings.reasoning_effort || "none");
  setFormValue(form, "text_verbosity", settings.text_verbosity || "medium");
  setFormValue(form, "image_detail", settings.image_detail || "original");
  form.elements.web_search.checked = Boolean(settings.web_search);
  form.elements.reasoning_summary.checked = Boolean(settings.reasoning_summary);
  form.elements.message_info_enabled.checked = settings.message_info_enabled !== false;
  setFormLines(form, "message_info_command_prefixes", settings.message_info_command_prefixes || ["/msg"]);
  setFormValue(form, "settings_store", settings.settings_store || "runtime/data/ai_settings.json");
}

function collectReplySettings() {
  const form = document.getElementById("replySettingsForm");
  return {
    system_prompt: form.elements.system_prompt.value.trim(),
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    wake_words: splitLines(form.elements.wake_words.value),
    reply_triggers: splitLines(form.elements.reply_triggers.value),
    context_limit: Number(form.elements.context_limit.value || 0),
    timeout_seconds: Number(form.elements.timeout_seconds.value || 0),
    max_tokens: Number(form.elements.max_tokens.value || 0),
    temperature: Number(form.elements.temperature.value || 0),
    reasoning_effort: form.elements.reasoning_effort.value,
    reasoning_summary: form.elements.reasoning_summary.checked,
    text_verbosity: form.elements.text_verbosity.value,
    web_search: form.elements.web_search.checked,
    message_info_enabled: form.elements.message_info_enabled.checked,
    message_info_command_prefixes: splitLines(form.elements.message_info_command_prefixes.value),
    image_detail: form.elements.image_detail.value,
    settings_store: form.elements.settings_store.value.trim(),
  };
}

function fillImageSettings(settings) {
  const form = document.getElementById("imageSettingsForm");
  if (!form) return;
  const normalized = normalizeImageSettings(settings || {});
  state.imageSettingsBaseline = normalized;
  setFormLines(form, "command_prefixes", normalized.command_prefixes);
  setFormLines(form, "size_commands", normalized.size_commands);
  setFormLines(form, "ratio_commands", normalized.ratio_commands);
  setFormLines(form, "send_mode_commands", normalized.send_mode_commands);
  setFormLines(form, "model_commands", normalized.model_commands);
  setFormValue(form, "size", normalized.size);
  setFormValue(form, "ratio", normalized.ratio);
  setFormValue(form, "quality", normalized.quality);
  setFormValue(form, "send_mode", normalized.send_mode);
  setFormValue(form, "timeout_seconds", normalized.timeout_seconds);
  setFormValue(form, "output_dir", normalized.output_dir);
  setFormValue(form, "settings_store", normalized.settings_store);
}

function normalizeImageSettings(settings) {
  return {
    command_prefixes: Array.isArray(settings.command_prefixes) ? settings.command_prefixes : [],
    size_commands: Array.isArray(settings.size_commands) ? settings.size_commands : [],
    ratio_commands: Array.isArray(settings.ratio_commands) ? settings.ratio_commands : [],
    send_mode_commands: Array.isArray(settings.send_mode_commands) ? settings.send_mode_commands : [],
    model_commands: Array.isArray(settings.model_commands) ? settings.model_commands : [],
    size: settings.size || "1K",
    ratio: settings.ratio || "1:1",
    quality: settings.quality || "standard",
    send_mode: settings.send_mode || "auto",
    timeout_seconds: Number(settings.timeout_seconds ?? 120),
    output_dir: settings.output_dir || "runtime/data/generated_images",
    settings_store: settings.settings_store || "runtime/data/image_settings.json",
  };
}

function collectImageSettings(onlyDirty = false) {
  const form = document.getElementById("imageSettingsForm");
  const current = {
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    size_commands: splitLines(form.elements.size_commands.value),
    ratio_commands: splitLines(form.elements.ratio_commands.value),
    send_mode_commands: splitLines(form.elements.send_mode_commands.value),
    model_commands: splitLines(form.elements.model_commands.value),
    size: form.elements.size.value,
    ratio: form.elements.ratio.value.trim(),
    quality: form.elements.quality.value,
    send_mode: form.elements.send_mode.value,
    timeout_seconds: Number(form.elements.timeout_seconds.value || 0),
    output_dir: form.elements.output_dir.value.trim(),
    settings_store: form.elements.settings_store.value.trim(),
  };
  if (!onlyDirty) return current;
  const baseline = state.imageSettingsBaseline || normalizeImageSettings({});
  return Object.fromEntries(
    Object.entries(current).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(baseline[key])),
  );
}

function fillGifSettings(settings) {
  const form = document.getElementById("gifSettingsForm");
  if (!form) return;
  setFormLines(form, "command_prefixes", settings.command_prefixes);
  setFormValue(form, "output_dir", settings.output_dir || "runtime/data/generated_gifs");
  setFormValue(form, "max_seconds", settings.max_seconds ?? 8);
  setFormValue(form, "fps", settings.fps ?? 12);
  setFormValue(form, "width", settings.width || "auto");
  setFormValue(form, "max_bytes", settings.max_bytes ?? 8388608);
}

function collectGifSettings() {
  const form = document.getElementById("gifSettingsForm");
  return {
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    output_dir: form.elements.output_dir.value.trim(),
    max_seconds: Number(form.elements.max_seconds.value || 0),
    fps: Number(form.elements.fps.value || 0),
    width: form.elements.width.value.trim() || "auto",
    max_bytes: Number(form.elements.max_bytes.value || 0),
  };
}

function setFormValue(form, name, value) {
  if (form.elements[name]) form.elements[name].value = value;
}

function setFormLines(form, name, value) {
  if (form.elements[name]) form.elements[name].value = Array.isArray(value) ? value.join("\n") : "";
}

async function saveAiServicesConfig() {
  const payload = {
    ai: {
      reply_provider: collectProviderForm("reply_provider"),
      image_provider: collectProviderForm("image_provider"),
    },
  };
  const result = await putJson("/api/ai", payload);
  document.getElementById("aiServiceSaveState").textContent = result.ok ? "已保存，后续 AI 请求会使用新的服务连接信息。" : "保存失败";
  await refreshAi();
  await refreshModules();
  return result;
}

async function saveAiReplyConfig() {
  const payload = {
    ai: {
      reply: collectReplySettings(),
    },
  };
  const result = await putJson("/api/ai", payload);
  document.getElementById("aiSaveState").textContent = result.ok ? "已保存，后续 AI 回复会使用新配置。" : "保存失败";
  await refreshAi();
  await refreshModules();
  return result;
}

async function saveAiImageConfig() {
  const payload = {
    ai: {
      image: collectImageSettings(true),
    },
  };
  const result = await putJson("/api/ai", payload);
  document.getElementById("imageSaveState").textContent = result.ok ? "已保存，后续 AI 生图会使用新配置。" : "保存失败";
  await refreshAi();
  await refreshModules();
  return result;
}

function fillDecryptSettings(settings) {
  const form = document.getElementById("decryptSettingsForm");
  if (!form) return;
  setFormValue(form, "timeout_seconds", settings.timeout_seconds || 120);
  setFormValue(form, "max_tokens", settings.max_tokens || 512);
  setFormValue(form, "image_detail", settings.image_detail || "original");
  setFormValue(form, "send_delay_ms", settings.send_delay_ms || 0);
  setFormValue(form, "state_store", settings.state_store || "runtime/data/ai_decrypt_claimed_ids.json");
  const list = document.getElementById("decryptTemplates");
  list.innerHTML = "";
  const templates = Array.isArray(settings.templates) ? settings.templates : [];
  templates.forEach((template) => list.appendChild(decryptTemplateForm(template)));
  if (!templates.length) {
    list.innerHTML = '<div class="empty-state">还没有解密模板。点击“新增模板”创建第一条解密规则。</div>';
  }
}

function newDecryptTemplate() {
  return {
    id: `decrypt_${Date.now()}`,
    name: "",
    enabled: true,
    trigger_keywords: ["解密红包"],
    id_markers: [],
    require_media: true,
    prompt: "",
  };
}

function addDecryptTemplate() {
  const list = document.getElementById("decryptTemplates");
  const empty = list.querySelector(".empty-state");
  if (empty) empty.remove();
  const card = decryptTemplateForm(newDecryptTemplate());
  list.appendChild(card);
  markViewDirty("moduleAiDecrypt");
  window.uiStudio?.onTemplateAdded?.("moduleAiDecrypt", card);
}

function decryptTemplateForm(template) {
  const card = document.createElement("section");
  card.className = "template-card";
  card.dataset.templateId = template.id || `decrypt_${Date.now()}`;
  card.dataset.templatePrompt = template.prompt || "";
  card.innerHTML = `
    <div class="template-head">
      <label class="inline-check"><input data-field="enabled" type="checkbox" ${template.enabled === false ? "" : "checked"}> 启用</label>
      <label class="inline-check"><input data-field="require_media" type="checkbox" ${template.require_media === false ? "" : "checked"}> 需要图片</label>
      <button class="danger" data-action="remove-decrypt-template">删除</button>
    </div>
    <div class="template-fields">
      <label><span>模板名称</span><input data-field="name" type="text" value="${escapeAttr(template.name || "")}" placeholder="九宫格骰子竞猜"></label>
      <label><span>触发关键词（全部命中）</span><textarea data-field="trigger_keywords" placeholder="九宫格骰子竞猜&#10;目标点数">${escapeHtml((template.trigger_keywords || []).join("\n"))}</textarea></label>
      <label><span>ID 标记</span><textarea data-field="id_markers" placeholder="红包ID:&#10;红包ID：">${escapeHtml((template.id_markers || []).join("\n"))}</textarea></label>
    </div>
  `;
  card.querySelector('[data-action="remove-decrypt-template"]').addEventListener("click", () => {
    card.remove();
    const list = document.getElementById("decryptTemplates");
    if (list && !list.querySelector(".template-card")) {
      list.innerHTML = '<div class="empty-state">还没有解密模板。点击“新增模板”创建第一条解密规则。</div>';
    }
  });
  return card;
}

function collectDecryptSettings() {
  const form = document.getElementById("decryptSettingsForm");
  return {
    timeout_seconds: Number(form.elements.timeout_seconds.value || 120),
    max_tokens: Number(form.elements.max_tokens.value || 512),
    image_detail: form.elements.image_detail.value,
    send_delay_ms: Number(form.elements.send_delay_ms.value || 0),
    state_store: form.elements.state_store.value.trim() || "runtime/data/ai_decrypt_claimed_ids.json",
    templates: Array.from(document.querySelectorAll("#decryptTemplates .template-card")).map((card) => ({
      id: card.dataset.templateId,
      name: card.querySelector('[data-field="name"]').value.trim(),
      enabled: card.querySelector('[data-field="enabled"]').checked,
      require_media: card.querySelector('[data-field="require_media"]').checked,
      trigger_keywords: splitRows(card.querySelector('[data-field="trigger_keywords"]').value),
      id_markers: splitRows(card.querySelector('[data-field="id_markers"]').value),
      prompt: card.dataset.templatePrompt || "",
    })),
  };
}

async function saveAiDecryptConfig() {
  const result = await putJson("/api/modules/ai_decrypt", { config: collectDecryptSettings() });
  const index = state.modules.findIndex((module) => module.id === "ai_decrypt");
  if (index >= 0) state.modules[index] = result.module;
  document.getElementById("decryptSaveState").textContent = result.ok ? "已保存，后续 AI 解密会使用新配置。" : "保存失败";
  fillDecryptSettings(result.module.config || {});
  await refreshModules();
  return result;
}

async function saveGifConfig() {
  const result = await putJson("/api/modules/gif", { config: collectGifSettings() });
  const index = state.modules.findIndex((module) => module.id === "gif");
  if (index >= 0) state.modules[index] = result.module;
  document.getElementById("gifSaveState").textContent = result.ok ? "已保存，后续 GIF 截取会使用新配置。" : "保存失败";
  fillGifSettings(result.module.config || {});
  await refreshModules();
  return result;
}

function fillUserProfileSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("userProfileSettingsForm");
  if (!form) return;
  setFormLines(form, "command_prefixes", config.command_prefixes || ["/profile", "/fx", ".fx", "画像", "用户画像"]);
  setFormValue(form, "default_sample_size", config.default_sample_size ?? 40);
  setFormValue(form, "min_sample_size", config.min_sample_size ?? 10);
  setFormValue(form, "max_sample_size", config.max_sample_size ?? 2000);
  setFormValue(form, "min_required_samples", config.min_required_samples ?? 8);
  setFormValue(form, "timeout_seconds", config.timeout_seconds ?? 180);
  setFormValue(form, "max_tokens", config.max_tokens ?? 4000);
  setFormValue(form, "style_prompt", config.style_prompt || "");
  const stateTag = document.getElementById("userProfileModuleState");
  stateTag.textContent = module.enabled ? "模块已启用" : "模块未启用";
  stateTag.className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  document.getElementById("userProfileSaveState").textContent = notice || "保存后新的画像命令会实时使用新配置。";
}

function collectUserProfileSettings() {
  const form = document.getElementById("userProfileSettingsForm");
  return {
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    default_sample_size: Number(form.elements.default_sample_size.value || 40),
    min_sample_size: Number(form.elements.min_sample_size.value || 10),
    max_sample_size: Number(form.elements.max_sample_size.value || 2000),
    min_required_samples: Number(form.elements.min_required_samples.value || 8),
    timeout_seconds: Number(form.elements.timeout_seconds.value || 180),
    max_tokens: Number(form.elements.max_tokens.value || 4000),
    style_prompt: form.elements.style_prompt.value.trim(),
  };
}

async function saveUserProfileConfig() {
  const result = await putJson("/api/modules/user_profile", { config: collectUserProfileSettings() });
  const index = state.modules.findIndex((module) => module.id === "user_profile");
  if (index >= 0) state.modules[index] = result.module;
  fillUserProfileSettings(result.module, result.ok ? "已保存，后续画像会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

function fillWordCloudSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("wordCloudSettingsForm");
  if (!form) return;
  setFormLines(form, "command_prefixes", config.command_prefixes || ["cy", "/cy"]);
  setFormValue(form, "default_limit", config.default_limit ?? 1000);
  setFormValue(form, "min_limit", config.min_limit ?? 50);
  setFormValue(form, "max_limit", config.max_limit ?? 2000);
  setFormValue(form, "width", config.width ?? 900);
  setFormValue(form, "height", config.height ?? 640);
  setFormValue(form, "output_dir", config.output_dir || "runtime/data/generated_word_clouds");
  setFormLines(form, "ignore_command_prefixes", config.ignore_command_prefixes || ["/", ".", ","]);
  setFormLines(form, "stop_words", config.stop_words || []);
  form.elements.delete_command.checked = config.delete_command !== false;
  document.getElementById("wordCloudModuleState").textContent = module.enabled ? "模块已启用" : "模块未启用";
  document.getElementById("wordCloudModuleState").className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  document.getElementById("wordCloudSaveState").textContent = notice || "保存后新的词云命令会实时使用新配置。";
}

function collectWordCloudSettings() {
  const form = document.getElementById("wordCloudSettingsForm");
  return {
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    default_limit: Number(form.elements.default_limit.value || 1000),
    min_limit: Number(form.elements.min_limit.value || 50),
    max_limit: Number(form.elements.max_limit.value || 2000),
    width: Number(form.elements.width.value || 900),
    height: Number(form.elements.height.value || 640),
    output_dir: form.elements.output_dir.value.trim() || "runtime/data/generated_word_clouds",
    ignore_command_prefixes: splitRows(form.elements.ignore_command_prefixes.value),
    stop_words: splitLines(form.elements.stop_words.value),
    delete_command: form.elements.delete_command.checked,
  };
}

async function saveWordCloudConfig() {
  const result = await putJson("/api/modules/word_cloud", { config: collectWordCloudSettings() });
  const index = state.modules.findIndex((module) => module.id === "word_cloud");
  if (index >= 0) state.modules[index] = result.module;
  fillWordCloudSettings(result.module, result.ok ? "已保存，后续词云命令会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

function fillQuoteSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("quoteSettingsForm");
  if (!form) return;
  setFormLines(form, "command_prefixes", config.command_prefixes || ["/q", "语录"]);
  setFormValue(form, "api_url", config.api_url || "");
  setFormValue(form, "sticker_set_short_name", config.sticker_set_short_name || "");
  setFormValue(form, "background_color", config.background_color || "#1b1429");
  setFormValue(form, "max_messages", config.max_messages ?? 5);
  setFormValue(form, "width", config.width ?? 512);
  setFormValue(form, "height", config.height ?? 768);
  setFormValue(form, "scale", config.scale ?? 2);
  setFormValue(form, "emoji_brand", config.emoji_brand || "apple");
  setFormValue(form, "timeout_seconds", config.timeout_seconds ?? 60);
  setFormValue(form, "tmp_dir", config.tmp_dir || "runtime/tmp");
  const stateTag = document.getElementById("quoteModuleState");
  if (stateTag) {
    stateTag.textContent = module.enabled ? "模块已启用" : "模块未启用";
    stateTag.className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  }
  document.getElementById("quoteSaveState").textContent = notice || "保存后新的语录命令会实时使用新配置。";
}

function collectQuoteSettings() {
  const form = document.getElementById("quoteSettingsForm");
  return {
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    api_url: form.elements.api_url.value.trim(),
    sticker_set_short_name: form.elements.sticker_set_short_name.value.trim(),
    background_color: form.elements.background_color.value.trim() || "#1b1429",
    max_messages: Number(form.elements.max_messages.value || 5),
    width: Number(form.elements.width.value || 512),
    height: Number(form.elements.height.value || 768),
    scale: Number(form.elements.scale.value || 2),
    emoji_brand: form.elements.emoji_brand.value.trim() || "apple",
    timeout_seconds: Number(form.elements.timeout_seconds.value || 60),
    tmp_dir: form.elements.tmp_dir.value.trim() || "runtime/tmp",
  };
}

async function saveQuoteConfig() {
  const result = await putJson("/api/modules/quote", { config: collectQuoteSettings() });
  const index = state.modules.findIndex((module) => module.id === "quote");
  if (index >= 0) state.modules[index] = result.module;
  fillQuoteSettings(result.module, result.ok ? "已保存，后续语录命令会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

function fillChatGamesSettings(module, notice = "") {
  const config = module.config || {};
  const lucky = config.lucky_word || {};
  const emoji = config.emoji_riddle || {};
  const decode = config.garbled_decode || {};
  const form = document.getElementById("chatGamesSettingsForm");
  if (!form) return;

  setFormValue(form, "state_store", config.state_store || "runtime/data/chat_games_state.json");
  setFormValue(form, "output_dir", config.output_dir || "runtime/data/generated_chat_games");

  form.elements.lucky_enabled.checked = lucky.enabled !== false;
  setFormLines(form, "lucky_words", lucky.words || []);
  setFormValue(form, "lucky_reward_text", lucky.reward_text || "+100");
  setFormValue(form, "lucky_daily_limit_per_chat", lucky.daily_limit_per_chat ?? 1);
  setFormValue(form, "lucky_per_user_daily_limit", lucky.per_user_daily_limit ?? 1);
  setFormValue(form, "lucky_min_message_length", lucky.min_message_length ?? 2);
  setFormLines(form, "lucky_ignore_command_prefixes", lucky.ignore_command_prefixes || ["/", ".", ",", "+"]);

  form.elements.emoji_enabled.checked = emoji.enabled !== false;
  setFormLines(form, "emoji_command_prefixes", emoji.command_prefixes || ["/emoji", "/emojiriddle", "图谜"]);
  setFormValue(form, "emoji_duration_seconds", emoji.duration_seconds ?? 20);
  setFormValue(form, "emoji_reward_text", emoji.reward_text || "+100");
  setFormValue(form, "emoji_winner_policy", emoji.winner_policy || "first");
  form.elements.emoji_announce_answer.checked = emoji.announce_answer !== false;
  form.elements.emoji_delete_command.checked = emoji.delete_command !== false;
  setFormValue(form, "emoji_items", formatEmojiItems(emoji.items || []));

  form.elements.decode_enabled.checked = decode.enabled !== false;
  setFormLines(form, "decode_command_prefixes", decode.command_prefixes || ["/decode", "/garble", "乱码"]);
  setFormValue(form, "decode_duration_seconds", decode.duration_seconds ?? 25);
  setFormValue(form, "decode_reward_text", decode.reward_text || "+100");
  setFormValue(form, "decode_winner_policy", decode.winner_policy || "first");
  form.elements.decode_announce_answer.checked = decode.announce_answer !== false;
  form.elements.decode_delete_command.checked = decode.delete_command !== false;
  setFormLines(form, "decode_phrases", decode.phrases || []);

  const stateTag = document.getElementById("chatGamesModuleState");
  if (stateTag) {
    stateTag.textContent = module.enabled ? "模块已启用" : "模块未启用";
    stateTag.className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  }
  document.getElementById("chatGamesSaveState").textContent = notice || "保存后新的小游戏请求会实时使用新配置。";
}

function formatEmojiItems(items) {
  if (!Array.isArray(items)) return "";
  return items
    .map((item) => {
      const answers = Array.isArray(item.answers) ? item.answers.join(",") : "";
      return [item.clue || "", answers, item.hint || ""].map((value) => String(value).trim()).join(" | ").replace(/\s+\|\s+$/, "");
    })
    .filter((line) => line.trim())
    .join("\n");
}

function parseEmojiItems(value) {
  return value
    .split(/\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("|").map((part) => part.trim());
      const clue = parts[0] || "";
      const answers = (parts[1] || "")
        .split(/[,，、/]/)
        .map((answer) => answer.trim())
        .filter(Boolean);
      return { clue, answers, hint: parts.slice(2).join(" | ").trim() };
    })
    .filter((item) => item.clue && item.answers.length);
}

function collectChatGamesSettings() {
  const form = document.getElementById("chatGamesSettingsForm");
  return {
    state_store: form.elements.state_store.value.trim() || "runtime/data/chat_games_state.json",
    output_dir: form.elements.output_dir.value.trim() || "runtime/data/generated_chat_games",
    lucky_word: {
      enabled: form.elements.lucky_enabled.checked,
      words: splitLines(form.elements.lucky_words.value),
      reward_text: form.elements.lucky_reward_text.value.trim() || "+100",
      daily_limit_per_chat: Number(form.elements.lucky_daily_limit_per_chat.value || 1),
      per_user_daily_limit: Number(form.elements.lucky_per_user_daily_limit.value || 1),
      ignore_command_prefixes: splitRows(form.elements.lucky_ignore_command_prefixes.value),
      min_message_length: Number(form.elements.lucky_min_message_length.value || 2),
    },
    emoji_riddle: {
      enabled: form.elements.emoji_enabled.checked,
      command_prefixes: splitLines(form.elements.emoji_command_prefixes.value),
      duration_seconds: Number(form.elements.emoji_duration_seconds.value || 20),
      reward_text: form.elements.emoji_reward_text.value.trim() || "+100",
      winner_policy: form.elements.emoji_winner_policy.value,
      announce_answer: form.elements.emoji_announce_answer.checked,
      delete_command: form.elements.emoji_delete_command.checked,
      items: parseEmojiItems(form.elements.emoji_items.value),
    },
    garbled_decode: {
      enabled: form.elements.decode_enabled.checked,
      command_prefixes: splitLines(form.elements.decode_command_prefixes.value),
      duration_seconds: Number(form.elements.decode_duration_seconds.value || 25),
      reward_text: form.elements.decode_reward_text.value.trim() || "+100",
      winner_policy: form.elements.decode_winner_policy.value,
      announce_answer: form.elements.decode_announce_answer.checked,
      delete_command: form.elements.decode_delete_command.checked,
      phrases: splitRows(form.elements.decode_phrases.value),
    },
  };
}

async function saveChatGamesConfig() {
  const result = await putJson("/api/modules/chat_games", { config: collectChatGamesSettings() });
  const index = state.modules.findIndex((module) => module.id === "chat_games");
  if (index >= 0) state.modules[index] = result.module;
  fillChatGamesSettings(result.module, result.ok ? "已保存，后续小游戏会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

function fillAutoForwardSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("autoForwardSettingsForm");
  setFormValue(form, "command_prefixes", (config.command_prefixes || [",re"]).join("\n"));
  setFormValue(form, "copy_text_command_prefixes", (config.copy_text_command_prefixes || [",copy"]).join("\n"));
  setFormValue(form, "quote_command_prefixes", (config.quote_command_prefixes || [",quote"]).join("\n"));
  setFormValue(form, "link_command_prefixes", (config.link_command_prefixes || [",link"]).join("\n"));
  form.elements.delete_command.checked = config.delete_command !== false;
  document.getElementById("autoForwardModuleState").textContent = module.enabled ? "模块已启用" : "模块未启用";
  document.getElementById("autoForwardModuleState").className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  document.getElementById("autoForwardSaveState").textContent = notice || "保存后新的转发命令会实时使用新配置。";
}

function collectAutoForwardSettings() {
  const form = document.getElementById("autoForwardSettingsForm");
  return {
    command_prefixes: splitRows(form.elements.command_prefixes.value),
    copy_text_command_prefixes: splitRows(form.elements.copy_text_command_prefixes.value),
    quote_command_prefixes: splitRows(form.elements.quote_command_prefixes.value),
    link_command_prefixes: splitRows(form.elements.link_command_prefixes.value),
    delete_command: form.elements.delete_command.checked,
  };
}

async function saveAutoForwardConfig() {
  const result = await putJson("/api/modules/auto_forward", { config: collectAutoForwardSettings() });
  const index = state.modules.findIndex((module) => module.id === "auto_forward");
  if (index >= 0) state.modules[index] = result.module;
  fillAutoForwardSettings(result.module, result.ok ? "已保存，后续自动转发会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

const MAGNET_IMPORT_STATUS = {
  downloading: "下载中",
  importing: "导入中",
  imported: "导入成功",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消",
  scanning: "扫描中",
  running: "处理中",
  unchanged: "无更新",
};

function fillMagnetImportSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("magnetImportSettingsForm");
  if (!form) return;
  setFormLines(form, "watch_chats", config.watch_chats || []);
  setFormLines(form, "sender_usernames", config.sender_usernames || []);
  setFormLines(form, "sender_ids", config.sender_ids || []);
  setFormValue(form, "file_name_pattern", config.file_name_pattern || "^x1080x.*\\.csv$");
  setFormValue(form, "max_file_size_mb", config.max_file_size_mb ?? 2048);
  setFormValue(form, "download_retries", config.download_retries ?? 5);
  setFormValue(form, "api_base_url", config.api_base_url || "");
  setFormValue(form, "api_username", config.api_username || "");
  setFormValue(form, "api_password", "");
  resetSecretInput(form.elements.api_password);
  setFormValue(form, "import_timeout_seconds", config.import_timeout_seconds ?? 1800);
  form.elements.update_existing.checked = Boolean(config.update_existing);
  form.elements.skip_duplicates.checked = config.skip_duplicates !== false;
  setFormValue(form, "reply_text", config.reply_text || "");
  setFormLines(form, "import_command_prefixes", config.import_command_prefixes || ["/import"]);
  form.elements.channel_enabled.checked = Boolean(config.channel_enabled);
  setFormValue(form, "channel_chat", config.channel_chat || "");
  setFormValue(form, "channel_url_prefix", config.channel_url_prefix || "");
  setFormValue(form, "channel_source_site", config.channel_source_site || "");
  setFormValue(form, "channel_forum_id", config.channel_forum_id || "");
  setFormValue(form, "channel_forum_type", config.channel_forum_type || "");
  setFormValue(form, "channel_batch_size", config.channel_batch_size ?? 500);
  form.elements.channel_enrich_images.checked = config.channel_enrich_images !== false;
  form.elements.channel_export_enabled.checked = Boolean(config.channel_export_enabled);
  setFormValue(form, "channel_export_chat", config.channel_export_chat || "");
  setFormValue(form, "channel_export_weekday", String(config.channel_export_weekday ?? 4));
  setFormValue(form, "channel_export_time", config.channel_export_time || "12:00");
  setFormValue(form, "channel_export_source_site", config.channel_export_source_site || "ltx");
  form.elements.avdb_enabled.checked = Boolean(config.avdb_enabled);
  setFormValue(form, "avdb_interval_hours", config.avdb_interval_hours ?? 4);
  setFormValue(form, "avdb_repo", config.avdb_repo || "");
  setFormValue(form, "avdb_asset_pattern", config.avdb_asset_pattern || "");
  setFormValue(form, "avdb_source_site", config.avdb_source_site || "ltx");
  const stateTag = document.getElementById("magnetImportModuleState");
  stateTag.textContent = module.enabled ? "模块已启用" : "模块未启用";
  stateTag.className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  const passwordTag = document.getElementById("magnetImportPasswordState");
  passwordTag.textContent = config.has_api_password ? "已配置密码" : "未配置密码";
  passwordTag.className = `tag ${config.has_api_password ? "enabled" : "disabled"}`;
  const metrics = module.metrics || {};
  document.getElementById("magnetImportCount").textContent = `累计导入 ${metrics.imported || 0} 次`;
  const last = metrics.last || {};
  document.getElementById("magnetImportLast").textContent = last.file
    ? `最近：${last.at || ""} ${last.file} · ${MAGNET_IMPORT_STATUS[last.status] || last.status}${last.detail ? ` · ${last.detail}` : ""}`
    : "暂无导入记录";
  const channel = metrics.channel || {};
  document.getElementById("magnetChannelCount").textContent = `频道累计新增 ${channel.imported || 0} 条`;
  document.getElementById("magnetChannelCursor").textContent = `已处理到消息 #${channel.last_message_id || 0}`;
  const scanButton = document.getElementById("magnetChannelFullScan");
  scanButton.disabled = Boolean(channel.scanning) || !module.enabled || !config.channel_enabled;
  scanButton.textContent = channel.scanning ? "频道扫描中…" : "全量提取频道";
  document.getElementById("magnetChannelRebuild").disabled = scanButton.disabled;
  const exportState = metrics.channel_export || {};
  document.getElementById("magnetExportCursor").textContent = `已导出到记录 #${exportState.last_record_id || 0}`;
  const avdb = metrics.avdb || {};
  document.getElementById("magnetAvdbTag").textContent = `AVDB 版本 ${avdb.last_tag || "-"}`;
  document.getElementById("magnetAvdbCount").textContent = `AVDB 累计新增 ${avdb.imported || 0} 条`;
  document.getElementById("magnetAvdbCheck").disabled = Boolean(avdb.running) || !module.enabled;
  document.getElementById("magnetAvdbCheck").textContent = avdb.running ? "AVDB 处理中…" : "立即检查更新";
  document.getElementById("magnetAvdbRebuild").disabled = Boolean(avdb.running) || !module.enabled;
  document.getElementById("magnetAvdbUpdate").disabled = Boolean(avdb.running) || !module.enabled;
  const avdbLast = avdb.last || {};
  const avdbSchedule = config.avdb_enabled ? `每 ${config.avdb_interval_hours ?? 4} 小时检查` : "定时检查未启用";
  document.getElementById("magnetAvdbLast").textContent = avdbLast.status
    ? `AVDB：${avdbSchedule} · 最近检查 ${avdb.last_check_at || "-"} · ${avdbLast.at || ""} ${avdbLast.detail || avdbLast.status}`
    : `AVDB：${avdbSchedule} · 暂无记录`;
  document.getElementById("magnetChannelExportNow").disabled = Boolean(exportState.running) || !module.enabled;
  const exportLast = exportState.last || {};
  const exportSchedule = config.channel_export_enabled
    ? `每${["周一", "周二", "周三", "周四", "周五", "周六", "周日"][config.channel_export_weekday ?? 4]} ${config.channel_export_time || "12:00"} 有新记录时全量导出`
    : "定时导出未启用";
  document.getElementById("magnetExportLast").textContent = exportLast.status
    ? `${exportSchedule} · 最近：${exportLast.at || ""} · ${exportLast.detail || exportLast.status}`
    : `${exportSchedule} · 暂无导出记录`;
  const channelLast = channel.last || {};
  document.getElementById("magnetChannelLast").textContent = channelLast.status
    ? `频道：${channelLast.at || ""} · ${MAGNET_IMPORT_STATUS[channelLast.status] || channelLast.status}${channelLast.detail ? ` · ${channelLast.detail}` : ""}`
    : "频道来源暂无记录";
  document.getElementById("magnetImportSaveState").textContent = notice || "保存后新收到的文件会使用新配置。";
}

function collectMagnetImportSettings() {
  const form = document.getElementById("magnetImportSettingsForm");
  const data = {
    watch_chats: splitLines(form.elements.watch_chats.value),
    sender_usernames: splitLines(form.elements.sender_usernames.value).map((item) => item.replace(/^@/, "")),
    sender_ids: splitLines(form.elements.sender_ids.value),
    file_name_pattern: form.elements.file_name_pattern.value.trim(),
    max_file_size_mb: Number(form.elements.max_file_size_mb.value || 2048),
    download_retries: Number(form.elements.download_retries.value || 5),
    api_base_url: form.elements.api_base_url.value.trim(),
    api_username: form.elements.api_username.value.trim(),
    import_timeout_seconds: Number(form.elements.import_timeout_seconds.value || 1800),
    update_existing: form.elements.update_existing.checked,
    skip_duplicates: form.elements.skip_duplicates.checked,
    reply_text: form.elements.reply_text.value.trim(),
    import_command_prefixes: splitLines(form.elements.import_command_prefixes.value),
    channel_enabled: form.elements.channel_enabled.checked,
    channel_chat: form.elements.channel_chat.value.trim(),
    channel_url_prefix: form.elements.channel_url_prefix.value.trim(),
    channel_source_site: form.elements.channel_source_site.value.trim(),
    channel_forum_id: form.elements.channel_forum_id.value.trim(),
    channel_forum_type: form.elements.channel_forum_type.value.trim(),
    channel_batch_size: Number(form.elements.channel_batch_size.value || 500),
    channel_enrich_images: form.elements.channel_enrich_images.checked,
    channel_export_enabled: form.elements.channel_export_enabled.checked,
    channel_export_chat: form.elements.channel_export_chat.value.trim(),
    channel_export_weekday: Number(form.elements.channel_export_weekday.value || 4),
    channel_export_time: form.elements.channel_export_time.value || "12:00",
    channel_export_source_site: form.elements.channel_export_source_site.value.trim(),
    avdb_enabled: form.elements.avdb_enabled.checked,
    avdb_interval_hours: Number(form.elements.avdb_interval_hours.value || 4),
    avdb_repo: form.elements.avdb_repo.value.trim(),
    avdb_asset_pattern: form.elements.avdb_asset_pattern.value.trim(),
    avdb_source_site: form.elements.avdb_source_site.value.trim(),
  };
  const password = form.elements.api_password.value;
  if (password) data.api_password = password;
  return data;
}

async function saveMagnetImportConfig() {
  const result = await putJson("/api/modules/magnet_import", { config: collectMagnetImportSettings() });
  const index = state.modules.findIndex((module) => module.id === "magnet_import");
  if (index >= 0) state.modules[index] = result.module;
  fillMagnetImportSettings(result.module, result.ok ? "已保存，新收到的文件会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

async function startMagnetChannelScan(rebuild = false) {
  const source = findModule("magnet_import")?.config?.channel_source_site || "频道";
  const question = rebuild
    ? `先删除 MagnetBoard 中来源为 ${source} 的全部记录，再从频道第一条消息重新解析导入（用于修正无码标记、补封面）？记录 id 会变化。`
    : "从频道第一条消息开始全量提取并导入 MagnetBoard？已存在的记录会被跳过。";
  if (!window.confirm(question)) return;
  const notice = document.getElementById("magnetImportSaveState");
  try {
    const result = await postJson("/api/modules/magnet_import/channel-scan", { full: true, rebuild });
    const index = state.modules.findIndex((module) => module.id === "magnet_import");
    if (index >= 0 && result.module) state.modules[index] = result.module;
    if (result.module) fillMagnetImportSettings(result.module, "频道全量提取已开始，进度见上方频道状态。");
  } catch (error) {
    notice.textContent = error.message;
  }
}

async function runMagnetChannelExport() {
  if (!window.confirm("立即导出该来源的全部记录并发送到群？")) return;
  const notice = document.getElementById("magnetImportSaveState");
  const button = document.getElementById("magnetChannelExportNow");
  button.disabled = true;
  try {
    const result = await postJson("/api/modules/magnet_import/channel-export", {});
    notice.textContent = result.result?.detail || "导出完成";
  } catch (error) {
    notice.textContent = error.message;
  } finally {
    await refreshModules();
    const module = findModule("magnet_import");
    if (module) fillMagnetImportSettings(module, notice.textContent);
  }
}

document.getElementById("magnetChannelFullScan").addEventListener("click", () => startMagnetChannelScan(false));
document.getElementById("magnetChannelRebuild").addEventListener("click", () => startMagnetChannelScan(true));
document.getElementById("magnetChannelExportNow").addEventListener("click", runMagnetChannelExport);

async function startMagnetAvdbRun(rebuild = false, updateExisting = false) {
  const source = findModule("magnet_import")?.config?.avdb_source_site || "ltx";
  const question = rebuild
    ? `先删除 MagnetBoard 中来源为 ${source} 的全部记录，再下载最新资源包重新导入？记录 id 会变化。`
    : updateExisting
      ? `下载最新资源包重新导入，并用资源包数据更新 MagnetBoard 中已有的 ${source} 记录（记录 id 不变）？`
      : "立即检查 GitHub 最新资源包并导入（版本未变化则不处理）？";
  if (!window.confirm(question)) return;
  const notice = document.getElementById("magnetImportSaveState");
  try {
    const result = await postJson("/api/modules/magnet_import/avdb-run", { force: false, rebuild, update_existing: updateExisting });
    const index = state.modules.findIndex((module) => module.id === "magnet_import");
    if (index >= 0 && result.module) state.modules[index] = result.module;
    if (result.module) fillMagnetImportSettings(result.module, "AVDB 任务已开始，进度见 AVDB 状态行（刷新页面更新）。");
  } catch (error) {
    notice.textContent = error.message;
  }
}

document.getElementById("magnetAvdbCheck").addEventListener("click", () => startMagnetAvdbRun(false));
document.getElementById("magnetAvdbRebuild").addEventListener("click", () => startMagnetAvdbRun(true));
document.getElementById("magnetAvdbUpdate").addEventListener("click", () => startMagnetAvdbRun(false, true));

const REX_WIDGET_STATUS = { added: "新增", updated: "更新", skipped: "跳过", failed: "失败", scan: "扫描" };

function fillRexWidgetSyncSettings(module, notice = "") {
  const config = module.config || {};
  const form = document.getElementById("rexWidgetSyncSettingsForm");
  if (!form) return;
  setFormValue(form, "channel_chat", config.channel_chat || "");
  setFormValue(form, "hub_base_url", config.hub_base_url || "");
  setFormValue(form, "hub_password", "");
  resetSecretInput(form.elements.hub_password);
  setFormValue(form, "collection_slug", config.collection_slug || "ExampleUser");
  setFormValue(form, "group_id", config.group_id || "");
  setFormValue(form, "file_name_pattern", config.file_name_pattern || "\\.js$");
  setFormValue(form, "exclude_name_pattern", config.exclude_name_pattern || "");
  setFormValue(form, "max_file_size_mb", config.max_file_size_mb ?? 25);
  setFormValue(form, "request_timeout_seconds", config.request_timeout_seconds ?? 120);
  form.elements.follow_links.checked = config.follow_links !== false;
  setFormLines(form, "ignore_keys", config.ignore_keys || []);
  form.elements.lock_title.checked = config.lock_title !== false;
  const stateTag = document.getElementById("rexWidgetModuleState");
  stateTag.textContent = module.enabled ? "模块已启用" : "模块未启用";
  stateTag.className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  const passwordTag = document.getElementById("rexWidgetPasswordState");
  passwordTag.textContent = config.has_hub_password ? "已配置密码" : "未配置密码";
  passwordTag.className = `tag ${config.has_hub_password ? "enabled" : "disabled"}`;
  const metrics = module.metrics || {};
  document.getElementById("rexWidgetCounts").textContent = `新增 ${metrics.added || 0} · 更新 ${metrics.updated || 0} · 跟踪 ${metrics.tracked || 0} 个`;
  document.getElementById("rexWidgetCursor").textContent = metrics.pending_from
    ? `已处理到 #${metrics.last_message_id || 0}（#${metrics.pending_from} 起待重试）`
    : `已处理到消息 #${metrics.last_message_id || 0}`;
  const last = metrics.last || {};
  document.getElementById("rexWidgetLast").textContent = last.status
    ? `最近：${last.at || ""} · ${REX_WIDGET_STATUS[last.status] || last.status} · ${last.title || ""} ${last.detail || ""}`
    : "暂无同步记录";
  const history = document.getElementById("rexWidgetHistory");
  history.replaceChildren(
    ...(metrics.history || []).slice(0, 12).map((item) => {
      const line = document.createElement("div");
      line.textContent = `${item.at || ""} · ${REX_WIDGET_STATUS[item.status] || item.status} · ${item.title || ""} ${item.detail || ""}`;
      return line;
    }),
  );
  const busy = Boolean(metrics.scanning) || !module.enabled;
  const fullButton = document.getElementById("rexWidgetFullScan");
  fullButton.disabled = busy;
  fullButton.textContent = metrics.scanning ? "同步中…" : "全量同步频道";
  document.getElementById("rexWidgetCatchUp").disabled = busy;
  document.getElementById("rexWidgetSyncSaveState").textContent = notice || "保存后新收到的帖子会使用新配置。";
}

function collectRexWidgetSyncSettings() {
  const form = document.getElementById("rexWidgetSyncSettingsForm");
  const data = {
    channel_chat: form.elements.channel_chat.value.trim(),
    hub_base_url: form.elements.hub_base_url.value.trim(),
    collection_slug: form.elements.collection_slug.value.trim(),
    group_id: form.elements.group_id.value.trim(),
    file_name_pattern: form.elements.file_name_pattern.value.trim(),
    exclude_name_pattern: form.elements.exclude_name_pattern.value.trim(),
    max_file_size_mb: Number(form.elements.max_file_size_mb.value || 25),
    request_timeout_seconds: Number(form.elements.request_timeout_seconds.value || 120),
    follow_links: form.elements.follow_links.checked,
    ignore_keys: splitLines(form.elements.ignore_keys.value),
    lock_title: form.elements.lock_title.checked,
  };
  const password = form.elements.hub_password.value;
  if (password) data.hub_password = password;
  return data;
}

async function saveRexWidgetSyncConfig() {
  const result = await putJson("/api/modules/rex_widget_sync", { config: collectRexWidgetSyncSettings() });
  const index = state.modules.findIndex((module) => module.id === "rex_widget_sync");
  if (index >= 0) state.modules[index] = result.module;
  fillRexWidgetSyncSettings(result.module, result.ok ? "已保存，新收到的帖子会使用新配置。" : "保存失败");
  await refreshModules();
  return result;
}

async function startRexWidgetScan(full) {
  const question = full
    ? "从频道第一条帖子开始全量同步到 Hub？每个模块只取最新一版，版本不高于 Hub 已有的会跳过。"
    : "从上次处理位置补漏同步？";
  if (!window.confirm(question)) return;
  const notice = document.getElementById("rexWidgetSyncSaveState");
  try {
    const result = await postJson("/api/modules/rex_widget_sync/scan", { full });
    const index = state.modules.findIndex((module) => module.id === "rex_widget_sync");
    if (index >= 0 && result.module) state.modules[index] = result.module;
    if (result.module) fillRexWidgetSyncSettings(result.module, "同步已开始，刷新页面查看进度。");
  } catch (error) {
    notice.textContent = error.message;
  }
}

document.getElementById("rexWidgetFullScan").addEventListener("click", () => startRexWidgetScan(true));
document.getElementById("rexWidgetCatchUp").addEventListener("click", () => startRexWidgetScan(false));

const CRON_FIELD_SPECS = [
  ["分钟", 0, 59],
  ["小时", 0, 23],
  ["日期", 1, 31],
  ["月份", 1, 12],
  ["星期", 0, 7],
];
const CRON_WEEKDAY_NAMES = {
  0: "周日",
  1: "周一",
  2: "周二",
  3: "周三",
  4: "周四",
  5: "周五",
  6: "周六",
};

function legacyTimesToCron(times) {
  if (!Array.isArray(times)) return "";
  const expressions = [];
  times.forEach((value) => {
    const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
    if (!match) return;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour > 23 || minute > 59) return;
    const expression = `${minute} ${hour} * * *`;
    if (!expressions.includes(expression)) expressions.push(expression);
  });
  return expressions.join("\n");
}

function splitCronExpressions(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeCronSchedule(value) {
  const expressions = splitCronExpressions(value);
  if (!expressions.length) throw new Error("Cron 表达式不能为空");
  return expressions
    .map((expression, index) => {
      try {
        return parseCronExpression(expression).source;
      } catch (error) {
        const prefix = expressions.length > 1 ? `第 ${index + 1} 行 ` : "";
        throw new Error(`${prefix}${error.message}`);
      }
    })
    .join("\n");
}

function parseCronExpression(expression) {
  const source = String(expression || "").trim().split(/\s+/).filter(Boolean).join(" ");
  const fields = source ? source.split(" ") : [];
  if (fields.length !== 5) throw new Error("Cron 表达式必须包含 5 个字段（分 时 日 月 周）");
  const values = fields.map((field, index) => {
    const [label, minimum, maximum] = CRON_FIELD_SPECS[index];
    return parseCronField(field, label, minimum, maximum, index === 4);
  });
  return {
    source,
    fields,
    minute: values[0],
    hour: values[1],
    day: values[2],
    month: values[3],
    weekday: values[4],
  };
}

function parseCronField(text, label, minimum, maximum, normalizeSunday = false) {
  const values = new Set();
  for (const part of String(text || "").split(",")) {
    if (!part) throw new Error(`Cron 的${label}字段包含空项`);
    const stepParts = part.split("/");
    if (stepParts.length > 2) throw new Error(`Cron 的${label}字段步长格式无效：${part}`);
    const base = stepParts[0];
    const hasStep = stepParts.length === 2;
    const step = hasStep ? cronInteger(stepParts[1], label, "步长") : 1;
    if (step <= 0) throw new Error(`Cron 的${label}字段步长必须大于 0`);

    let start;
    let end;
    if (base === "*") {
      start = minimum;
      end = maximum;
    } else if (base.includes("-")) {
      const range = base.split("-");
      if (range.length !== 2) throw new Error(`Cron 的${label}字段范围无效：${base}`);
      start = cronInteger(range[0], label, "范围起点");
      end = cronInteger(range[1], label, "范围终点");
    } else {
      start = cronInteger(base, label, "值");
      end = hasStep ? maximum : start;
    }
    if (start < minimum || start > maximum || end < minimum || end > maximum) {
      throw new Error(`Cron 的${label}字段必须在 ${minimum}–${maximum} 之间：${part}`);
    }
    if (start > end) throw new Error(`Cron 的${label}字段范围起点不能大于终点：${part}`);
    for (let value = start; value <= end; value += step) {
      values.add(normalizeSunday && value === 7 ? 0 : value);
    }
  }
  return Array.from(values).sort((left, right) => left - right);
}

function cronInteger(value, label, kind) {
  if (!/^\d+$/.test(String(value || ""))) {
    throw new Error(`Cron 的${label}字段${kind}必须是整数：${value || "空"}`);
  }
  return Number(value);
}

function cronWildcardStep(value) {
  const match = String(value || "").match(/^\*\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

function fixedCronTimes(parsed) {
  if (parsed.hour.length * parsed.minute.length > 12) return [];
  const times = [];
  parsed.hour.forEach((hour) => {
    parsed.minute.forEach((minute) => times.push(`${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`));
  });
  return times;
}

function describeCronSchedule(value) {
  return splitCronExpressions(normalizeCronSchedule(value)).map(describeCronExpression).join("；");
}

function describeCronExpression(expression) {
  const parsed = parseCronExpression(expression);
  const [minuteText, hourText, dayText, monthText, weekdayText] = parsed.fields;
  const minuteStep = cronWildcardStep(minuteText);
  if (minuteStep && [hourText, dayText, monthText, weekdayText].every((item) => item === "*")) {
    return `每隔 ${minuteStep} 分钟发送一次`;
  }
  if (parsed.source === "* * * * *") return "每分钟发送一次";

  const times = fixedCronTimes(parsed);
  const timeDescription = times.join("、");
  const dayStep = cronWildcardStep(dayText);
  if (dayStep && monthText === "*" && weekdayText === "*" && timeDescription) {
    return `每月从 1 日开始每隔 ${dayStep} 天，于 ${timeDescription} 发送`;
  }
  if (dayText === "*" && monthText === "*" && weekdayText !== "*" && timeDescription) {
    const weekdays = [1, 2, 3, 4, 5, 6, 0]
      .filter((value) => parsed.weekday.includes(value))
      .map((value) => CRON_WEEKDAY_NAMES[value])
      .join("、");
    return `每${weekdays} ${timeDescription} 发送`;
  }
  if (dayText === "*" && monthText === "*" && weekdayText === "*" && timeDescription) {
    const hourStep = cronWildcardStep(hourText);
    if (hourStep && parsed.minute.length === 1) {
      return `每隔 ${hourStep} 小时的第 ${String(parsed.minute[0]).padStart(2, "0")} 分钟发送一次`;
    }
    return `每天 ${timeDescription} 发送`;
  }
  if (dayText === "*" && monthText === "*" && weekdayText === "*" && hourText === "*" && parsed.minute.length === 1) {
    return `每小时第 ${String(parsed.minute[0]).padStart(2, "0")} 分钟发送`;
  }
  if (monthText === "*" && weekdayText === "*" && timeDescription && parsed.day.length <= 8) {
    return `每月 ${parsed.day.map((value) => `${value} 日`).join("、")} ${timeDescription} 发送`;
  }
  if (weekdayText === "*" && timeDescription && parsed.month.length <= 4 && parsed.day.length <= 4) {
    const months = parsed.month.map((value) => `${value} 月`).join("、");
    const days = parsed.day.map((value) => `${value} 日`).join("、");
    return `每年 ${months} ${days} ${timeDescription} 发送`;
  }
  return `按 Cron「${parsed.source}」执行`;
}

function updateCronSummary(card) {
  const input = card.querySelector('[data-field="cron"]');
  const summary = card.querySelector(".cron-summary");
  if (!input || !summary) return false;
  try {
    summary.textContent = `当前通知方式：${describeCronSchedule(input.value)}`;
    summary.className = "cron-summary valid";
    input.setCustomValidity("");
    input.setAttribute("aria-invalid", "false");
    return true;
  } catch (error) {
    summary.textContent = `配置有误：${error.message}`;
    summary.className = "cron-summary invalid";
    input.setCustomValidity(error.message);
    input.setAttribute("aria-invalid", "true");
    return false;
  }
}

function showCheckinSettings(module, notice = "") {
  const tasks = Array.isArray(module.config?.tasks) ? module.config.tasks : [];
  document.getElementById("checkinModuleState").textContent = module.enabled ? "模块已启用" : "模块未启用";
  document.getElementById("checkinModuleState").className = `tag ${module.enabled ? "enabled" : "disabled"}`;
  document.getElementById("checkinTaskCount").textContent = `签到 ${tasks.length} 个`;
  document.getElementById("checkinSaveState").textContent = notice || "保存后自动签到调度会实时使用新配置。";
  renderCheckinTargetOptions();
  const list = document.getElementById("checkinTasks");
  list.innerHTML = "";
  tasks.forEach((task) => list.appendChild(checkinTaskForm(task)));
  if (!tasks.length) {
    list.innerHTML = '<div class="empty-state">还没有签到任务。点击“新增签到”创建第一个定时消息。</div>';
  }
}

function addCheckinTask() {
  const list = document.getElementById("checkinTasks");
  const empty = list.querySelector(".empty-state");
  if (empty) empty.remove();
  const card = checkinTaskForm(newCheckinTask());
  list.appendChild(card);
  document.getElementById("checkinTaskCount").textContent = `签到 ${list.querySelectorAll(".template-card").length} 个`;
  markViewDirty("moduleCheckin");
  window.uiStudio?.onTemplateAdded?.("moduleCheckin", card);
}

function newCheckinTask() {
  return {
    id: `checkin_${Date.now()}`,
    name: "",
    enabled: true,
    target: "",
    target_title: "",
    cron: "0 9 * * *",
    message: "签到",
  };
}

function checkinTaskForm(task) {
  const card = document.createElement("section");
  card.className = "template-card";
  card.dataset.taskId = task.id || `checkin_${Date.now()}`;
  const schedule = String(task.cron || "").trim() || legacyTimesToCron(task.times) || "0 9 * * *";
  card.innerHTML = `
    <div class="template-head">
      <label class="inline-check"><input data-field="enabled" type="checkbox" ${task.enabled === false ? "" : "checked"}> 启用</label>
      <button class="danger" data-action="remove-checkin-task">删除</button>
    </div>
    <div class="template-fields">
      <label><span>任务名称</span><input data-field="name" type="text" value="${escapeAttr(task.name || "")}" placeholder="每日签到"></label>
      <label><span>目标群组/Bot</span><input data-field="target" list="checkinTargetOptions" type="text" value="${escapeAttr(task.target || "")}" placeholder="-100... / @bot_username"></label>
      <div class="cron-field wide-field">
        <label>
          <span>Cron 表达式</span>
          <textarea data-field="cron" rows="2" spellcheck="false" autocapitalize="off" placeholder="0 9 * * *">${escapeHtml(schedule)}</textarea>
        </label>
        <div class="cron-order">字段顺序：分　时　日　月　周；需要多个独立时间时可每行填写一条。</div>
        <div class="cron-examples" aria-label="Cron 快捷示例">
          <span>快捷填入</span>
          <button type="button" data-cron="*/30 * * * *">每 30 分钟</button>
          <button type="button" data-cron="0 9 * * *">每天 09:00</button>
          <button type="button" data-cron="0 9 */3 * *">每隔 3 天 09:00</button>
          <button type="button" data-cron="0 9 * * 1">每周一 09:00</button>
          <button type="button" data-cron="0 9 * * 1-5">工作日 09:00</button>
        </div>
        <div class="cron-summary" role="status" aria-live="polite"></div>
      </div>
      <label class="wide-field"><span>发送内容</span><textarea data-field="message" rows="3" placeholder="签到">${escapeHtml(task.message || "")}</textarea></label>
    </div>
  `;
  const cronInput = card.querySelector('[data-field="cron"]');
  cronInput.addEventListener("input", () => updateCronSummary(card));
  card.querySelectorAll("[data-cron]").forEach((button) => {
    button.addEventListener("click", () => {
      cronInput.value = button.dataset.cron;
      updateCronSummary(card);
      cronInput.focus();
    });
  });
  card.querySelector('[data-action="remove-checkin-task"]').addEventListener("click", () => {
    card.remove();
    const list = document.getElementById("checkinTasks");
    const count = list.querySelectorAll(".template-card").length;
    document.getElementById("checkinTaskCount").textContent = `签到 ${count} 个`;
    if (!count) list.innerHTML = '<div class="empty-state">还没有签到任务。点击“新增签到”创建第一个定时消息。</div>';
  });
  updateCronSummary(card);
  return card;
}

function collectCheckinSettings() {
  return {
    tasks: Array.from(document.querySelectorAll("#checkinTasks .template-card")).map((card, index) => {
      const target = card.querySelector('[data-field="target"]').value.trim();
      const targetItem = state.checkinTargets.find((item) => item.id === target || item.username === target || `@${item.username}` === target);
      const cronInput = card.querySelector('[data-field="cron"]');
      let cron;
      try {
        cron = normalizeCronSchedule(cronInput.value);
      } catch (error) {
        updateCronSummary(card);
        cronInput.focus();
        cronInput.reportValidity();
        const name = card.querySelector('[data-field="name"]').value.trim() || `第 ${index + 1} 个签到任务`;
        throw new Error(`${name}：${error.message}`);
      }
      return {
        id: card.dataset.taskId,
        name: card.querySelector('[data-field="name"]').value.trim(),
        enabled: card.querySelector('[data-field="enabled"]').checked,
        target,
        target_title: targetItem?.title || "",
        cron,
        message: card.querySelector('[data-field="message"]').value.trim(),
      };
    }),
  };
}

async function loadCheckinTargets() {
  const stateLabel = document.getElementById("checkinTargetState");
  stateLabel.textContent = "正在加载群组和 Bot...";
  try {
    const data = await getJson("/api/telegram-targets");
    state.checkinTargets = data.targets || [];
    renderCheckinTargetOptions();
    stateLabel.textContent = data.error ? `加载失败：${data.error}` : `已加载 ${state.checkinTargets.length} 个目标`;
  } catch (error) {
    stateLabel.textContent = `加载失败：${error.message}`;
  }
}

function renderCheckinTargetOptions() {
  let options = document.getElementById("checkinTargetOptions");
  if (!options) {
    options = document.createElement("datalist");
    options.id = "checkinTargetOptions";
    document.body.appendChild(options);
  }
  options.innerHTML = state.checkinTargets
    .map((item) => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.title)} · ${escapeHtml(item.kind)}${item.username ? ` · @${escapeHtml(item.username)}` : ""}</option>`)
    .join("");
}

async function saveCheckinConfig() {
  const result = await putJson("/api/modules/checkin", { config: collectCheckinSettings() });
  const index = state.modules.findIndex((module) => module.id === "checkin");
  if (index >= 0) state.modules[index] = result.module;
  showCheckinSettings(result.module, result.ok ? "已保存并实时生效。" : "保存失败");
  await refreshModules();
  return result;
}

async function refreshAiUsage() {
  try {
    const range = document.getElementById("usageRange").value;
    const data = await getJson(`/api/ai/usage?range=${encodeURIComponent(range)}`);
    renderUsage(data);
  } catch (error) {
    showToast(`加载 AI 用量统计失败：${error.message}`, "error");
  }
}

function renderUsage(data) {
  state.lastUsageData = data;
  const summary = data.summary || {};
  const series = data.series || [];
  const requestSeries = series.map((item) => Number(item.requests || 0));
  const tokenSeries = series.map((item) => Number(item.total_tokens || 0));
  const kpis = [
    {
      key: "requests",
      label: "请求总数",
      value: formatNumber(summary.requests),
      sub: `<span class="dot success"></span>成功 ${formatNumber(summary.success)} <span class="dot failed"></span>失败 ${formatNumber(summary.failed)}`,
      color: chartToken("--chart-kpi-requests", "#475569"),
      fillTop: chartToken("--chart-kpi-requests-top", "rgba(71, 85, 105, 0.22)"),
      values: requestSeries,
    },
    {
      key: "tokens",
      label: "Token 总数",
      value: compactNumber(summary.total_tokens),
      sub: `输入 ${compactNumber(summary.input_tokens)} / 输出 ${compactNumber(summary.output_tokens)}`,
      color: chartToken("--chart-kpi-tokens", "#2563eb"),
      fillTop: chartToken("--chart-kpi-tokens-top", "rgba(37, 99, 235, 0.22)"),
      values: tokenSeries,
    },
    {
      key: "rpm",
      label: "RPM",
      value: Number(summary.rpm || 0).toFixed(2),
      sub: `请求总数 ${formatNumber(summary.requests)} · 平均耗时 ${formatMs(summary.avg_latency_ms)}`,
      color: chartToken("--chart-kpi-rpm", "#0b7a75"),
      fillTop: chartToken("--chart-kpi-rpm-top", "rgba(11, 122, 117, 0.24)"),
      values: requestSeries,
    },
    {
      key: "tpm",
      label: "TPM",
      value: formatUsageRate(summary.tpm),
      sub: `Token 总数 ${compactNumber(summary.total_tokens)}`,
      color: chartToken("--chart-kpi-tpm", "#c27803"),
      fillTop: chartToken("--chart-kpi-tpm-top", "rgba(194, 120, 3, 0.22)"),
      values: tokenSeries,
    },
  ];
  document.getElementById("usageKpis").innerHTML = kpis
    .map(
      (item) => `
        <article class="usage-card usage-card-${item.key}">
          <div class="usage-card-top">
            <span>${item.label}</span>
            <b></b>
          </div>
          <strong>${item.value}</strong>
          <small>${item.sub}</small>
          <canvas id="usageSpark-${item.key}" class="usage-sparkline" height="68"></canvas>
        </article>
      `,
    )
    .join("");
  kpis.forEach((item) => {
    drawUsageSparkline(`usageSpark-${item.key}`, item.values, item.color, item.fillTop);
  });
  renderUsageRows("usageModelRows", data.models || [], "model");
  renderUsageRows("usageFeatureRows", data.features || [], "feature");

  const rangeVal = document.getElementById("usageRange")?.value || "today";
  if (rangeVal === "today" || !document.getElementById("kpiAiValue")?.dataset.populated) {
    const kpiAiValue = document.getElementById("kpiAiValue");
    const kpiAiSub = document.getElementById("kpiAiSub");
    if (kpiAiValue) {
      kpiAiValue.textContent = `${compactNumber(summary.total_tokens || 0)} tok`;
      kpiAiValue.dataset.populated = "1";
    }
    if (kpiAiSub) {
      kpiAiSub.textContent = `请求 ${formatNumber(summary.requests || 0)} 次 · 平均耗时 ${formatMs(summary.avg_latency_ms || 0)}`;
    }
  }
}

function renderUsageRows(targetId, rows, labelKey) {
  const target = document.getElementById(targetId);
  if (!rows.length) {
    const colspan = labelKey === "model" ? 7 : 5;
    target.innerHTML = `<tr><td colspan="${colspan}">暂无记录</td></tr>`;
    return;
  }
  target.innerHTML = rows
    .map((row) => {
      if (labelKey === "model") {
        return `<tr><td>${escapeHtml(row.model)}</td><td>${formatNumber(row.requests)}</td><td>${formatNumber(row.total_tokens)}</td><td>${formatNumber(row.input_tokens)}</td><td>${formatNumber(row.output_tokens)}</td><td>${formatMs(row.avg_latency_ms)}</td><td>${formatRate(row.success_rate)}</td></tr>`;
      }
      return `<tr><td>${escapeHtml(row.feature)}</td><td>${formatNumber(row.requests)}</td><td>${formatNumber(row.total_tokens)}</td><td>${formatMs(row.avg_latency_ms)}</td><td>${formatRate(row.success_rate)}</td></tr>`;
    })
    .join("");
}

function drawUsageSparkline(canvasId, values, color, fillTop) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const normalized = values.length ? values : [0];
  drawLineChart(canvas, [{ values: normalized, color, fillTop }], Math.max(...normalized, 1), { compact: true });
}

let logProgrammaticScroll = false;

function logRecordKey(record) {
  if (!record || typeof record !== "object") return "";
  return `${record.time || ""}|${record.level || ""}|${record.name || ""}|${record.message || ""}`;
}

function scrollLogsToBottom(smooth = false) {
  const box = document.getElementById("liveLogs");
  if (!box) return;
  logProgrammaticScroll = true;
  if (smooth && typeof box.scrollTo === "function") {
    box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  } else {
    box.scrollTop = box.scrollHeight;
  }
  window.setTimeout(() => {
    logProgrammaticScroll = false;
  }, 80);
  document.getElementById("logScrollBottomBtn")?.classList.add("hidden");
}

function syncLogToolbarUI() {
  const scrollBtn = document.getElementById("toggleLogAutoScrollBtn");
  if (scrollBtn) {
    const active = Boolean(state.logAutoScroll);
    scrollBtn.setAttribute("aria-pressed", String(active));
    scrollBtn.classList.toggle("is-paused", !active);
    scrollBtn.innerHTML = `<span class="nav-ico mini-ico">${iconSvg(active ? "pause" : "play")}</span><span>${active ? "暂停滚动" : "恢复滚动"}</span>`;
  }
  const wrapBtn = document.getElementById("toggleLogWrapBtn");
  if (wrapBtn) {
    const wrapped = Boolean(state.logWordWrap);
    wrapBtn.setAttribute("aria-pressed", String(wrapped));
    wrapBtn.classList.toggle("is-active", wrapped);
  }
  const box = document.getElementById("liveLogs");
  if (box) {
    box.classList.toggle("nowrap", !state.logWordWrap);
  }
  document.querySelectorAll("[data-log-tab]").forEach((tab) => {
    const isSel = tab.dataset.logTab === state.logSourceTab;
    tab.classList.toggle("active", isSel);
    tab.setAttribute("aria-selected", String(isSel));
  });
  document.getElementById("logArchiveStrip")?.classList.toggle("hidden", state.logSourceTab !== "archive");
  const titleEl = document.getElementById("logSourceTitle");
  if (titleEl) {
    titleEl.textContent = state.logsViewingFile && state.activeLogFile ? state.activeLogFile : "系统日志";
  }
}

async function switchLogTab(tab) {
  const next = tab === "archive" ? "archive" : "live";
  state.logSourceTab = next;
  if (next === "live") {
    state.logsViewingFile = false;
    state.activeLogFile = "";
    syncLogToolbarUI();
    updateLogRefreshState();
    await refreshLogs();
    return;
  }
  syncLogToolbarUI();
  await refreshLogFiles();
  if (!state.activeLogFile && state.logFilesList.length) {
    await readLogFile(state.logFilesList[0].name);
  } else if (state.activeLogFile) {
    await readLogFile(state.activeLogFile);
  } else {
    state.logsViewingFile = true;
    state.logFileContent = "";
    renderLogOutput();
    updateLogRefreshState("暂无历史日志归档文件");
  }
}

async function refreshLogs() {
  state.logClearedCursor = "";
  if (state.logSourceTab === "archive" && state.activeLogFile) {
    await readLogFile(state.activeLogFile);
    await refreshLogFiles();
    return;
  }
  state.logSourceTab = "live";
  state.logsViewingFile = false;
  state.activeLogFile = "";
  syncLogToolbarUI();
  try {
    await refreshRecentLogs();
    await refreshLogFiles();
    updateLogRefreshState();
  } catch (error) {
    showToast(`刷新日志失败：${error.message}`, "error");
  }
}

async function refreshRecentLogs() {
  const recent = await getJson("/api/logs/recent");
  state.recentLogRecords = Array.isArray(recent.records) ? recent.records : [];
  renderLogOutput();
}

function highlightLogText(text, query) {
  const safe = escapeHtml(text);
  if (!query) return safe;
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  try {
    return safe.replace(new RegExp(escapedQuery, "gi"), (match) => `<mark class="log-hit">${match}</mark>`);
  } catch (_e) {
    return safe;
  }
}

function renderLogOutput() {
  const box = document.getElementById("liveLogs");
  if (!box) return;
  const levelFilter = state.logLevelFilter || "ALL";
  const query = (state.logSearchQuery || "").trim();
  const queryLower = query.toLowerCase();

  let linesHtml = [];
  let totalCount = 0;
  let filteredCount = 0;

  if (state.logsViewingFile) {
    const rawLines = String(state.logFileContent || "").split(/\r?\n/).filter((l) => l.length > 0);
    totalCount = rawLines.length;
    rawLines.forEach((line) => {
      const match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(?:\[([^\]]+)\]\s*)?(.*)$/i);
      const lvl = match ? match[2].toUpperCase() : "";
      if (levelFilter !== "ALL") {
        if (levelFilter === "WARNING" && lvl !== "WARNING" && lvl !== "WARN") return;
        if (levelFilter === "ERROR" && lvl !== "ERROR" && lvl !== "CRITICAL") return;
        if (levelFilter !== "WARNING" && levelFilter !== "ERROR" && lvl !== levelFilter) return;
      }
      if (queryLower && !line.toLowerCase().includes(queryLower)) return;
      filteredCount += 1;
      if (match) {
        const [, ts, level, loggerName, msg] = match;
        const lvlClass = `lvl-${level.toLowerCase()}`;
        linesHtml.push(
          `<span class="log-line ${lvlClass}-row"><span class="log-ts">[${escapeHtml(ts)}]</span> <span class="log-lvl ${lvlClass}">${escapeHtml(level)}</span>${loggerName ? ` <span class="log-logger">${escapeHtml(loggerName)}:</span>` : ""} <span class="log-msg">${highlightLogText(msg, query)}</span></span>`,
        );
      } else {
        linesHtml.push(`<span class="log-line"><span class="log-msg">${highlightLogText(line, query)}</span></span>`);
      }
    });
  } else {
    let records = state.recentLogRecords || [];
    if (state.logClearedCursor) {
      let cutIdx = -1;
      for (let i = records.length - 1; i >= 0; i -= 1) {
        if (logRecordKey(records[i]) === state.logClearedCursor) {
          cutIdx = i;
          break;
        }
      }
      if (cutIdx >= 0) records = records.slice(cutIdx + 1);
    }
    totalCount = records.length;
    records.forEach((record) => {
      const level = String(record.level || "INFO").toUpperCase();
      if (levelFilter !== "ALL") {
        if (levelFilter === "WARNING" && level !== "WARNING" && level !== "WARN") return;
        if (levelFilter === "ERROR" && level !== "ERROR" && level !== "CRITICAL") return;
        if (levelFilter !== "WARNING" && levelFilter !== "ERROR" && level !== levelFilter) return;
      }
      const fullLine = `[${record.time || ""}] ${level} ${record.name || ""}: ${record.message || ""}`;
      if (queryLower && !fullLine.toLowerCase().includes(queryLower)) return;
      filteredCount += 1;
      const lvlClass = `lvl-${level.toLowerCase()}`;
      linesHtml.push(
        `<span class="log-line ${lvlClass}-row"><span class="log-ts">[${escapeHtml(record.time || "")}]</span> <span class="log-lvl ${lvlClass}">${escapeHtml(level)}</span> <span class="log-logger">${escapeHtml(record.name || "")}:</span> <span class="log-msg">${highlightLogText(record.message || "", query)}</span></span>`,
      );
    });
  }

  box.innerHTML = linesHtml.length ? linesHtml.join("") : '<span class="log-empty-hint">当前筛选条件下暂无日志输出</span>';
  const countEl = document.getElementById("logLineCount");
  if (countEl) countEl.textContent = `${filteredCount} / ${totalCount} 行`;
  if (state.logAutoScroll && !state.logsViewingFile) {
    window.requestAnimationFrame(() => scrollLogsToBottom(false));
  }
}

async function refreshLogFiles() {
  const files = await getJson("/api/logs/files");
  const list = Array.isArray(files.files) ? files.files : [];
  state.logFilesList = list;
  const countBadge = document.getElementById("logArchiveCount");
  if (countBadge) countBadge.textContent = String(list.length);

  const fileList = document.getElementById("logFiles");
  if (!fileList) return;
  fileList.innerHTML = "";
  if (!list.length) {
    fileList.innerHTML = '<div class="empty-state">暂无历史日志文件</div>';
    return;
  }
  list.forEach((file) => {
    const row = document.createElement("div");
    row.className = `log-archive-chip ${state.activeLogFile === file.name ? "active" : ""}`;
    row.innerHTML = `
      <button type="button" class="log-archive-select" data-file="${escapeAttr(file.name)}" title="${escapeAttr(file.name)}">
        <span class="log-archive-name">${escapeHtml(file.name)}</span>
        <span class="log-archive-size">${formatBytes(file.size)}</span>
      </button>
      <a class="log-archive-dl" href="/api/logs/download?file=${encodeURIComponent(file.name)}" title="下载 ${escapeAttr(file.name)}" aria-label="下载 ${escapeAttr(file.name)}">${iconSvg("download")}</a>
    `;
    row.querySelector("button")?.addEventListener("click", () => void readLogFile(file.name));
    fileList.appendChild(row);
  });
}

async function readLogFile(name) {
  try {
    const data = await getJson(`/api/logs/read?file=${encodeURIComponent(name)}&lines=800`);
    state.logSourceTab = "archive";
    state.logsViewingFile = true;
    state.activeLogFile = name;
    state.logFileContent = data.content || "";
    syncLogToolbarUI();
    renderLogOutput();
    document.querySelectorAll("#logFiles .log-archive-chip").forEach((row) => {
      row.classList.toggle("active", row.querySelector("button")?.dataset.file === name);
    });
    updateLogRefreshState(`正在查看历史归档 ${name}（最近 800 行），可点击右上角下载完整日志。`);
    window.requestAnimationFrame(() => scrollLogsToBottom(false));
  } catch (error) {
    showToast(`读取日志失败：${error.message}`, "error");
  }
}

function updateLogRefreshState(message = "") {
  const label = document.getElementById("logRefreshState");
  if (!label) return;
  if (message) {
    label.textContent = message;
    return;
  }
  const intervalText = formatRefreshInterval(state.logRefreshIntervalSeconds);
  label.textContent = state.logAutoRefresh
    ? `Telebot 本体运行日志，每 ${intervalText} 秒自动拉取。`
    : "Telebot 本体运行日志（自动拉取已暂停）。";
}

function handleLogRefreshIntervalChange(event, formatValue = true) {
  const seconds = parseRefreshInterval(event.target.value);
  if (seconds === null) return;
  state.logRefreshIntervalSeconds = seconds;
  localStorage.setItem(LOG_REFRESH_INTERVAL_KEY, String(seconds));
  if (formatValue) event.target.value = formatRefreshInterval(seconds);
  updateLogRefreshState();
  scheduleLogRefreshLoop();
}

function loadLogRefreshIntervalSeconds() {
  return parseRefreshInterval(localStorage.getItem(LOG_REFRESH_INTERVAL_KEY)) || DEFAULT_LOG_REFRESH_INTERVAL_SECONDS;
}

function parseRefreshInterval(value) {
  const seconds = Number.parseFloat(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return Math.max(MIN_LOG_REFRESH_INTERVAL_SECONDS, Math.round(seconds * 1000) / 1000);
}

function formatRefreshInterval(seconds) {
  return Number(seconds).toFixed(3).replace(/\.?0+$/, "");
}

function scheduleLogRefreshLoop() {
  if (logRefreshTimer) window.clearTimeout(logRefreshTimer);
  if (!state.logAutoRefresh) return;
  logRefreshTimer = window.setTimeout(runLogRefreshLoop, state.logRefreshIntervalSeconds * 1000);
}

async function runLogRefreshLoop() {
  const logsView = document.getElementById("logs");
  if (logsView?.classList.contains("active") && state.logAutoRefresh && !state.logsViewingFile && !logRefreshInFlight) {
    logRefreshInFlight = true;
    try {
      await refreshRecentLogs();
      updateLogRefreshState();
    } catch (error) {
      document.getElementById("logRefreshState").textContent = `自动刷新失败：${error.message}`;
    } finally {
      logRefreshInFlight = false;
    }
  }
  scheduleLogRefreshLoop();
}

async function refreshSettings() {
  const data = await getJson("/api/settings");
  state.settings = data;
  rememberGroupNamesFromConfig(data.telegram?.monitored_group_meta || {});
  if (!state.groups.length) {
    renderGroupsFromConfig(data.telegram.monitored_groups);
  } else {
    updateGroupCount();
  }
}

async function loadGroups() {
  const stateLabel = document.getElementById("groupLoadState");
  document.getElementById("groupList").classList.remove("collapsed");
  stateLabel.textContent = "正在加载 Telegram 群组...";
  try {
    const data = await getJson("/api/groups");
    state.groups = data.groups || [];
    rememberGroupNames(state.groups);
    renderGroupList();
    stateLabel.textContent = `已加载 ${state.groups.length} 个群组`;
  } catch (error) {
    stateLabel.textContent = `加载失败：${error.message}`;
    renderGroupsFromConfig(state.settings?.telegram?.monitored_groups || []);
  }
}

function renderGroupsFromConfig(groups) {
  const list = document.getElementById("groupList");
  list.innerHTML = "";
  if (!groups.length) {
    list.innerHTML = '<div class="empty-state">当前没有监听群组。点击“加载群组”后可以从账号可见群组中勾选。</div>';
  } else {
    groups.forEach((id) => {
      const cached = groupMetaForId(id);
      list.appendChild(groupOption({ id, title: cached.title || id, username: cached.username || "", kind: cached.kind || "configured", selected: true }));
    });
  }
  updateGroupCount();
}

function renderGroupList() {
  const list = document.getElementById("groupList");
  list.innerHTML = "";
  if (!state.groups.length) {
    list.innerHTML = '<div class="empty-state">没有加载到可选群组，请确认 Telegram 登录态可用。</div>';
    updateGroupCount();
    return;
  }
  state.groups.forEach((group) => list.appendChild(groupOption(group)));
  applyGroupSearchFilter();
  updateGroupCount();
}

function applyGroupSearchFilter() {
  const query = (state.groupSearchQuery || "").trim().toLowerCase();
  document.querySelectorAll("#groupList .group-option").forEach((card) => {
    if (!query) {
      card.classList.remove("hidden");
      return;
    }
    const text = (card.textContent || "").toLowerCase();
    card.classList.toggle("hidden", !text.includes(query));
  });
}

function groupOption(group) {
  const label = document.createElement("label");
  label.className = "group-option";
  const username = group.username ? `@${group.username}` : "无 username";
  label.innerHTML = `
    <input type="checkbox" value="${escapeHtml(group.id)}" ${group.selected ? "checked" : ""}>
    <span class="group-main">
      <strong>${escapeHtml(group.title || group.id)}</strong>
      <small>${escapeHtml(group.id)} · ${escapeHtml(username)}</small>
    </span>
    <span class="group-kind">${escapeHtml(group.kind || "group")}</span>
  `;
  label.querySelector("input").addEventListener("change", updateGroupCount);
  return label;
}

function selectedGroups() {
  return Array.from(document.querySelectorAll('#groupList input[type="checkbox"]:checked')).map((input) => input.value);
}

function updateGroupCount() {
  const groups = selectedGroups();
  setGroupCount(groups.length);
  renderSelectedGroupNames(groups);
}

function setGroupCount(count) {
  document.getElementById("groupCount").textContent = `已选择 ${count} 个群组`;
}

function renderSelectedGroupNames(groupIds = selectedGroups()) {
  const host = ensureSelectedGroupNamesHost();
  if (!host) return;
  host.innerHTML = "";
  if (!groupIds.length) {
    host.innerHTML = '<span class="hint">当前没有已选择的监听群组。</span>';
    window.uiStudio?.onSettingsUpdated?.(groupIds);
    return;
  }
  groupIds.forEach((id) => {
    const meta = groupMetaForId(id);
    const chip = document.createElement("span");
    chip.className = "selected-group-chip";
    chip.innerHTML = `<span>${escapeHtml(meta.title || id)}</span><small>${escapeHtml(id)}</small>`;
    host.appendChild(chip);
  });
  window.uiStudio?.onSettingsUpdated?.(groupIds);
}

function ensureSelectedGroupNamesHost() {
  let host = document.getElementById("selectedGroupNames");
  if (host) return host;
  const summary = document.querySelector("#settings .group-summary");
  if (!summary) return null;
  host = document.createElement("div");
  host.id = "selectedGroupNames";
  host.className = "selected-group-names";
  summary.insertAdjacentElement("afterend", host);
  return host;
}

function groupMetaForId(id) {
  const normalized = String(id || "").trim();
  const group = state.groups.find((item) => {
    const username = String(item.username || "").trim();
    return item.id === normalized || username === normalized || (username && `@${username}` === normalized);
  });
  if (group) return group;
  const configMeta = state.settings?.telegram?.monitored_group_meta?.[normalized];
  if (configMeta) return configMeta;
  return state.groupNameCache[normalized] || {};
}

function rememberGroupNames(groups) {
  let changed = false;
  groups.forEach((group) => {
    const id = String(group?.id || "").trim();
    if (!id) return;
    state.groupNameCache[id] = {
      title: String(group.title || id),
      username: String(group.username || ""),
      kind: String(group.kind || "group"),
    };
    changed = true;
  });
  if (changed) saveGroupNameCache();
}

function rememberGroupNamesFromConfig(groupMeta) {
  if (!groupMeta || typeof groupMeta !== "object") return;
  const groups = Object.entries(groupMeta).map(([id, meta]) => ({
    id,
    title: meta?.title || id,
    username: meta?.username || "",
    kind: meta?.kind || "group",
  }));
  rememberGroupNames(groups);
}

function selectedGroupMeta(groupIds) {
  return Object.fromEntries(
    groupIds.map((id) => {
      const meta = groupMetaForId(id);
      return [
        id,
        {
          title: String(meta.title || id),
          username: String(meta.username || ""),
          kind: String(meta.kind || "group"),
        },
      ];
    }),
  );
}

function loadGroupNameCache() {
  try {
    const data = JSON.parse(localStorage.getItem(GROUP_NAME_CACHE_KEY) || "{}");
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch {
    return {};
  }
}

function saveGroupNameCache() {
  try {
    localStorage.setItem(GROUP_NAME_CACHE_KEY, JSON.stringify(state.groupNameCache));
  } catch {
    // This cache only improves display labels; settings still work without it.
  }
}

async function saveGroups() {
  const groups = selectedGroups();
  const result = await putJson("/api/settings", { telegram: { monitored_groups: groups, monitored_group_meta: selectedGroupMeta(groups) } });
  state.settings = result.settings;
  rememberGroupNamesFromConfig(result.settings?.telegram?.monitored_group_meta || {});
  if (state.status?.telegram) {
    state.status.telegram.monitored_groups = groups;
  }
  setGroupCount(groups.length);
  renderSelectedGroupNames(groups);
  document.getElementById("groupList").classList.add("collapsed");
  document.getElementById("groupLoadState").textContent = "已保存并实时生效；再次点击“加载群组”可重新展开";
  await refreshStatus();
  return result;
}

function loadMetricHistory() {
  try {
    const data = JSON.parse(localStorage.getItem(METRIC_HISTORY_KEY) || "[]");
    if (Array.isArray(data)) {
      state.metricHistory = computeRates(pruneMetricHistory(data.map(normalizeMetricSample).filter(Boolean)));
    }
  } catch {
    state.metricHistory = [];
  }
}

function saveMetricHistory() {
  try {
    localStorage.setItem(METRIC_HISTORY_KEY, JSON.stringify(state.metricHistory));
  } catch {
    // History is nice to keep, but the dashboard should still work if storage is full or blocked.
  }
}

function ingestMetricHistory(data) {
  const incoming = Array.isArray(data.history) && data.history.length ? data.history : [sampleFromStatus(data)];
  const merged = new Map();
  state.metricHistory.forEach((sample) => {
    const normalized = normalizeMetricSample(sample);
    if (normalized) merged.set(Math.round(normalized.ts / 1000), normalized);
  });
  incoming.forEach((sample) => {
    const normalized = normalizeMetricSample(sample);
    if (normalized) merged.set(Math.round(normalized.ts / 1000), normalized);
  });
  state.metricHistory = computeRates(pruneMetricHistory([...merged.values()]));
  saveMetricHistory();
}

function sampleFromStatus(data) {
  const stats = data.system?.stats || {};
  return {
    ts: Date.now(),
    cpu: Number(data.metrics?.cpu_percent || 0),
    memory: Number(stats.memory_percent || 0),
    upload_bytes: Number(stats.upload_bytes || 0),
    download_bytes: Number(stats.download_bytes || 0),
  };
}

function normalizeMetricSample(sample) {
  if (!sample || typeof sample !== "object") return null;
  let ts = Number(sample.ts || 0);
  if (!ts) return null;
  if (ts < 10_000_000_000) ts *= 1000;
  return {
    ts,
    cpu: Number(sample.cpu || 0),
    memory: Number(sample.memory || 0),
    uploadBytes: Number(sample.uploadBytes ?? sample.upload_bytes ?? 0),
    downloadBytes: Number(sample.downloadBytes ?? sample.download_bytes ?? 0),
  };
}

function pruneMetricHistory(samples) {
  const cutoff = Date.now() - METRIC_MAX_AGE_MS;
  return samples
    .filter((sample) => sample.ts >= cutoff)
    .sort((a, b) => a.ts - b.ts)
    .slice(-METRIC_MAX_POINTS);
}

function computeRates(samples) {
  return samples.map((sample, index) => {
    const previous = samples[index - 1];
    if (!previous) return { ...sample, uploadRate: 0, downloadRate: 0 };
    const seconds = Math.max((sample.ts - previous.ts) / 1000, 1);
    const uploadDelta = sample.uploadBytes - previous.uploadBytes;
    const downloadDelta = sample.downloadBytes - previous.downloadBytes;
    return {
      ...sample,
      uploadRate: uploadDelta >= 0 ? uploadDelta / seconds : 0,
      downloadRate: downloadDelta >= 0 ? downloadDelta / seconds : 0,
    };
  });
}

function visibleMetricHistory() {
  const windowMs = CHART_WINDOWS[state.chartWindow] ?? CHART_WINDOWS["15m"];
  if (!Number.isFinite(windowMs)) return state.metricHistory;
  const newest = state.metricHistory.at(-1)?.ts || Date.now();
  const cutoff = newest - windowMs;
  const visible = state.metricHistory.filter((sample) => sample.ts >= cutoff);
  return visible.length ? visible : state.metricHistory.slice(-2);
}

function chartToken(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function drawCharts() {
  const history = visibleMetricHistory();
  const timestamps = history.map((item) => item.ts);
  const speedMax = Math.max(
    ...history.flatMap((item) => [item.downloadRate || 0, item.uploadRate || 0]),
    1024,
  );
  drawLineChart(document.getElementById("resourceChart"), [
    {
      label: "CPU",
      values: history.map((item) => item.cpu),
      color: chartToken("--chart-cpu", "#14d4a2"),
      fillTop: chartToken("--chart-cpu-top", "rgba(20, 212, 162, 0.26)"),
      fillBottom: chartToken("--chart-cpu-bottom", "rgba(20, 212, 162, 0.01)"),
      format: (v) => `${Number(v || 0).toFixed(1)}%`,
    },
    {
      label: "内存",
      values: history.map((item) => item.memory),
      color: chartToken("--chart-mem", "#38bdf8"),
      fillTop: chartToken("--chart-mem-top", "rgba(56, 189, 248, 0.22)"),
      fillBottom: chartToken("--chart-mem-bottom", "rgba(56, 189, 248, 0.01)"),
      format: (v) => `${Number(v || 0).toFixed(1)}%`,
    },
  ], 100, {
    timestamps,
    tooltipId: "resourceChartTooltip",
    formatAxis: (v) => `${Math.round(v)}%`,
  });
  drawLineChart(document.getElementById("speedChart"), [
    {
      label: "下载",
      values: history.map((item) => item.downloadRate || 0),
      color: chartToken("--chart-down", "#38bdf8"),
      fillTop: chartToken("--chart-down-top", "rgba(56, 189, 248, 0.24)"),
      fillBottom: chartToken("--chart-down-bottom", "rgba(56, 189, 248, 0.01)"),
      format: (v) => formatBytesPerSecond(v || 0),
    },
    {
      label: "上传",
      values: history.map((item) => item.uploadRate || 0),
      color: chartToken("--chart-up", "#34d399"),
      fillTop: chartToken("--chart-up-top", "rgba(52, 211, 153, 0.24)"),
      fillBottom: chartToken("--chart-up-bottom", "rgba(52, 211, 153, 0.01)"),
      format: (v) => formatBytesPerSecond(v || 0),
    },
  ], speedMax, {
    timestamps,
    tooltipId: "speedChartTooltip",
    formatAxis: (v) => formatBytesPerSecond(v),
  });
}

function formatChartTime(ts) {
  if (!ts) return "--:--:--";
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function drawLineChart(canvas, series, maxValue, options = {}) {
  if (!canvas) return;
  const compact = Boolean(options.compact);
  const hoverIndex = Number.isInteger(options.hoverIndex) ? options.hoverIndex : -1;
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = rect.width || canvas.clientWidth || Number(canvas.getAttribute("width")) || 300;
  const height = rect.height || canvas.clientHeight || Number(canvas.getAttribute("height")) || 180;
  if (width <= 0 || height <= 0) return;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const gridColor = chartToken("--chart-grid", "rgba(226, 238, 252, 0.07)");
  const axisColor = chartToken("--chart-axis", "#64768c");
  const ringColor = chartToken("--chart-ring", "#11161f");
  const rootFs = parseFloat(getComputedStyle(document.documentElement).fontSize) || 14;
  const axisFontPx = Math.max(11, Math.round(rootFs * 0.78));
  const axisFont = `500 ${axisFontPx}px ${chartToken("--font-mono", "ui-monospace, monospace")}`;
  const safeMax = Math.max(Number(maxValue) || 1, 1e-6);
  const padTop = compact ? 6 : 16;
  const padBottom = compact ? 4 : 12;
  const padRight = compact ? 2 : 12;

  let padLeft = compact ? 2 : 52;
  const steps = 3;
  const axisLabels = [];
  if (!compact && options.formatAxis) {
    ctx.save();
    ctx.font = axisFont;
    let maxLabelW = 0;
    for (let i = 0; i <= steps; i += 1) {
      const text = options.formatAxis(safeMax * (1 - i / steps));
      axisLabels.push(text);
      maxLabelW = Math.max(maxLabelW, ctx.measureText(text).width);
    }
    ctx.restore();
    padLeft = Math.max(46, Math.ceil(maxLabelW) + 16);
  }

  const plotHeight = Math.max(height - padTop - padBottom, 12);
  const plotWidth = Math.max(width - padLeft - padRight, 12);
  const baselineY = height - padBottom;

  if (!compact) {
    ctx.save();
    ctx.strokeStyle = gridColor;
    ctx.fillStyle = axisColor;
    ctx.font = axisFont;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    for (let i = 0; i <= steps; i += 1) {
      const y = Math.round(padTop + (plotHeight / steps) * i) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padLeft, y);
      ctx.lineTo(width - padRight, y);
      ctx.stroke();
      if (axisLabels[i] !== undefined) {
        ctx.fillText(axisLabels[i], padLeft - 10, y);
      }
    }
    ctx.restore();
  }

  let sampleCount = 0;
  const allPoints = [];

  series.forEach((line) => {
    const raw = line.values.length > 1 ? line.values : [line.values[0] || 0, line.values[0] || 0];
    sampleCount = Math.max(sampleCount, raw.length);
    const step = plotWidth / Math.max(raw.length - 1, 1);
    const points = raw.map((value, index) => {
      const clamped = Math.max(0, Math.min(Number(value) || 0, safeMax));
      return {
        x: padLeft + index * step,
        y: baselineY - (clamped / safeMax) * plotHeight,
        rawValue: Number(value) || 0,
      };
    });
    allPoints.push({ line, points });

    const tracePath = () => {
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      if (points.length === 2) {
        ctx.lineTo(points[1].x, points[1].y);
      } else {
        for (let i = 0; i < points.length - 1; i += 1) {
          const current = points[i];
          const next = points[i + 1];
          const midX = (current.x + next.x) / 2;
          const midY = (current.y + next.y) / 2;
          if (i === 0) ctx.lineTo(midX, midY);
          else ctx.quadraticCurveTo(current.x, current.y, midX, midY);
        }
        const last = points[points.length - 1];
        const prev = points[points.length - 2];
        ctx.quadraticCurveTo(prev.x, prev.y, last.x, last.y);
      }
    };

    tracePath();
    ctx.lineTo(points[points.length - 1].x, baselineY);
    ctx.lineTo(points[0].x, baselineY);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, padTop, 0, baselineY);
    gradient.addColorStop(0, line.fillTop || line.fill || "rgba(20, 212, 162, 0.22)");
    gradient.addColorStop(1, line.fillBottom || "rgba(20, 212, 162, 0)");
    ctx.fillStyle = gradient;
    ctx.fill();

    tracePath();
    ctx.strokeStyle = line.color;
    ctx.lineWidth = compact ? 1.9 : 2.25;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    if (!compact && points.length) {
      const tail = points[points.length - 1];
      ctx.beginPath();
      ctx.arc(tail.x, tail.y, 3.8, 0, Math.PI * 2);
      ctx.fillStyle = ringColor;
      ctx.fill();
      ctx.lineWidth = 2.1;
      ctx.strokeStyle = line.color;
      ctx.stroke();
    }
  });

  if (!compact && hoverIndex >= 0 && hoverIndex < sampleCount && allPoints.length) {
    const x = allPoints[0].points[Math.min(hoverIndex, allPoints[0].points.length - 1)].x;
    ctx.save();
    ctx.strokeStyle = chartToken("--accent-border", "rgba(20, 212, 162, 0.4)");
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, padTop);
    ctx.lineTo(Math.round(x) + 0.5, baselineY);
    ctx.stroke();
    ctx.restore();

    allPoints.forEach(({ line, points }) => {
      const pt = points[Math.min(hoverIndex, points.length - 1)];
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 4.8, 0, Math.PI * 2);
      ctx.fillStyle = ringColor;
      ctx.fill();
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = line.color;
      ctx.stroke();
    });
  }

  if (!compact && options.tooltipId) {
    canvas._chartMeta = { series, maxValue, options, padLeft, plotWidth, sampleCount, width, height };
    bindChartHover(canvas);
  }
}

function bindChartHover(canvas) {
  if (canvas._hoverBound) return;
  canvas._hoverBound = true;
  canvas.addEventListener("mousemove", (event) => {
    const meta = canvas._chartMeta;
    if (!meta || meta.sampleCount < 2) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, (x - meta.padLeft) / Math.max(meta.plotWidth, 1)));
    const idx = Math.round(ratio * (meta.sampleCount - 1));
    drawLineChart(canvas, meta.series, meta.maxValue, { ...meta.options, hoverIndex: idx });

    const tip = document.getElementById(meta.options.tooltipId);
    if (!tip) return;
    const tsList = meta.options.timestamps || [];
    const ts = tsList[Math.min(idx, tsList.length - 1)];
    tip.innerHTML = `
      <div class="chart-tooltip-time">${formatChartTime(ts)}</div>
      ${meta.series.map((s) => {
        const val = s.values[Math.min(idx, s.values.length - 1)] || 0;
        return `<div class="chart-tooltip-row"><span style="color:${s.color}">● ${escapeHtml(s.label || "")}</span><strong>${escapeHtml(s.format ? s.format(val) : String(val))}</strong></div>`;
      }).join("")}
    `;
    tip.classList.remove("hidden");
    const tipWidth = tip.offsetWidth || 160;
    const desiredLeft = x + 14 + tipWidth > rect.width ? Math.max(8, x - tipWidth - 14) : x + 14;
    tip.style.left = `${Math.round(desiredLeft)}px`;
  });
  canvas.addEventListener("mouseleave", () => {
    const meta = canvas._chartMeta;
    if (!meta) return;
    const tip = document.getElementById(meta.options.tooltipId);
    if (tip) tip.classList.add("hidden");
    drawLineChart(canvas, meta.series, meta.maxValue, { ...meta.options, hoverIndex: -1 });
  });
}

let redirectingToLogin = false;

async function getJson(url) {
  const response = await fetch(url);
  if (response.status === 401) {
    redirectToLogin();
    return new Promise(() => {});
  }
  if (!response.ok) {
    const text = await response.text();
    try {
      const data = JSON.parse(text);
      throw new Error(data.error || `${url} failed: ${response.status}`);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error(text || `${url} failed: ${response.status}`);
      }
      throw error;
    }
  }
  return response.json();
}

async function putJson(url, payload) {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (response.status === 401) {
    redirectToLogin();
    return new Promise(() => {});
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${url} failed: ${response.status}`);
  return data;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (response.status === 401) {
    redirectToLogin();
    return new Promise(() => {});
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${url} failed: ${response.status}`);
  return data;
}

function redirectToLogin() {
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search + window.location.hash)}`);
}

function addKv(list, key, value) {
  const dt = document.createElement("dt");
  dt.textContent = key;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function formatBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function formatBytesPerSecond(value) {
  return `${formatBytes(value)}/s`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function compactNumber(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 10_000) return `${(number / 1_000).toFixed(2)}K`;
  return formatNumber(number);
}

function formatUsageRate(value) {
  const number = Number(value || 0);
  if (number >= 1000) return Math.round(number).toLocaleString("zh-CN");
  return number.toFixed(2);
}

function formatMs(value) {
  const ms = Number(value || 0);
  if (!ms) return "0 ms";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

function formatRate(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function formatDuration(seconds) {
  const days = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (days) return `${days} 天 ${h} 小时`;
  if (h) return `${h} 小时 ${m} 分钟`;
  return `${m} 分钟`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

let statusPollTimer = null;
let statusPollInFlight = false;

function scheduleStatusLoop() {
  if (statusPollTimer) window.clearTimeout(statusPollTimer);
  statusPollTimer = window.setTimeout(async () => {
    if (!statusPollInFlight && !document.hidden) {
      statusPollInFlight = true;
      try {
        await refreshStatus();
      } catch (_error) {
        // 服务重启或短暂断网时静默等待下一次轮询恢复
      } finally {
        statusPollInFlight = false;
      }
    }
    scheduleStatusLoop();
  }, 5000);
}

/* ---------- Workspace Enhancements: Rail, Density, Command Palette, Dirty Bar, Filters ---------- */

function closeMobileNav() {
  document.body.classList.remove("mobile-nav-open");
}

function applyDensity(density, persist = false) {
  const normalized = ["compact", "comfortable", "spacious"].includes(density) ? density : "comfortable";
  document.documentElement.dataset.density = normalized;
  if (persist) {
    try {
      localStorage.setItem(DENSITY_STORAGE_KEY, normalized);
    } catch (_e) {}
    window.uiStudio?.onDensityChanged?.(normalized);
  }
  document.querySelectorAll("[data-density-option]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.densityOption === normalized);
  });
  window.requestAnimationFrame(() => {
    drawCharts();
    if (state.lastUsageData) renderUsage(state.lastUsageData);
  });
}

function toggleSidebarRail() {
  const collapsed = document.documentElement.dataset.sidebar === "collapsed";
  if (collapsed) {
    delete document.documentElement.dataset.sidebar;
  } else {
    document.documentElement.dataset.sidebar = "collapsed";
  }
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "expanded" : "collapsed");
  } catch (_e) {}
  window.uiStudio?.onSidebarToggled?.(!collapsed);
  window.setTimeout(() => {
    drawCharts();
    if (state.lastUsageData) renderUsage(state.lastUsageData);
  }, 240);
}

function markViewDirty(viewId) {
  if (!viewId) return;
  const view = document.getElementById(viewId);
  if (!view) return;
  if (!view.dataset.saveBtn && viewId !== "moduleRedPacket") return;
  state.dirtyViews.add(viewId);
  syncDirtySaveBar();
}

function clearViewDirty(viewId) {
  if (!viewId) return;
  state.dirtyViews.delete(viewId);
  syncDirtySaveBar();
}

function syncDirtySaveBar() {
  const bar = document.getElementById("dirtySaveBar");
  if (!bar) return;
  const activeId = state.currentView || document.querySelector(".view.active")?.id;
  bar.classList.toggle("hidden", !activeId || !state.dirtyViews.has(activeId));
}

let cmdSelectedIndex = 0;
let cmdFilteredItems = [];

function buildCommandItems() {
  const items = [];
  Object.entries(titles).forEach(([viewId, [name, subtitle]]) => {
    const modEntry = Object.entries(moduleViewMap).find(([, vId]) => vId === viewId);
    const mod = modEntry ? findModule(modEntry[0]) : null;
    items.push({
      group: mod ? "功能模块" : "导航页面",
      title: name,
      subtitle,
      icon: viewIconMap[viewId] || "dashboard",
      tag: mod ? (mod.enabled ? "已启用" : "未启用") : "页面",
      keywords: `${name} ${subtitle} ${viewId} ${mod?.id || ""} ${mod?.description || ""}`.toLowerCase(),
      run: () => showView(viewId),
    });
  });

  state.modules.forEach((mod) => {
    items.push({
      group: "快捷开关",
      title: `${mod.enabled ? "停用" : "启用"}「${mod.name}」`,
      subtitle: mod.enabled ? "立即关闭该模块" : "立即开启该模块",
      icon: moduleIconKey(mod.id),
      tag: mod.enabled ? "关闭" : "开启",
      keywords: `toggle 开关 启用 停用 禁用 ${mod.name} ${mod.id}`.toLowerCase(),
      run: async () => {
        try {
          await toggleModuleEnabled(mod.id, !mod.enabled);
          showToast(`${mod.name} 已${mod.enabled ? "停用" : "启用"}`, "success");
        } catch (error) {
          showToast(`切换失败：${error.message}`, "error");
        }
      },
    });
  });

  items.push(
    {
      group: "界面与控制",
      title: "打开外观与背景设置",
      subtitle: "自定义壁纸、毛玻璃透明度、动态背景与交互",
      icon: "palette",
      tag: "外观",
      keywords: "appearance wallpaper skin glass blur bg 外观 皮肤 壁纸 背景 动态 玻璃".toLowerCase(),
      run: () => window.uiStudio?.openAppearanceModal?.(),
    },
    {
      group: "界面与控制",
      title: currentTheme() === "dark" ? "切换为瓷白浅色主题" : "切换为暗夜深色主题",
      subtitle: "立即切换全局深浅配色",
      icon: currentTheme() === "dark" ? "sun" : "moon",
      tag: "主题",
      keywords: "theme dark light 主题 深色 浅色 暗黑".toLowerCase(),
      run: () => applyTheme(currentTheme() === "dark" ? "light" : "dark", true),
    },
    {
      group: "界面与控制",
      title: "收起 / 展开左侧导航栏",
      subtitle: "切换宽导航与图标轨模式",
      icon: "sidebarToggle",
      tag: "布局",
      keywords: "sidebar rail 侧边栏 折叠 图标".toLowerCase(),
      run: () => toggleSidebarRail(),
    },
    {
      group: "界面与控制",
      title: "刷新全部运行数据",
      subtitle: "重新拉取状态、模块、AI 用量与日志",
      icon: "trend",
      tag: "刷新",
      keywords: "refresh reload 刷新 重载 同步".toLowerCase(),
      run: () => {
        void refreshAll()
          .then(() => showToast("全部数据已刷新", "success"))
          .catch((error) => showToast(`刷新失败：${error.message}`, "error"));
      },
    },
    {
      group: "界面与控制",
      title: "密度：紧凑 / 标准 / 舒适",
      subtitle: "循环切换界面排版密度",
      icon: "settings",
      tag: "密度",
      keywords: "density compact comfortable spacious 密度 缩放 4k".toLowerCase(),
      run: () => {
        const order = ["compact", "comfortable", "spacious"];
        const curr = document.documentElement.dataset.density || "comfortable";
        const next = order[(order.indexOf(curr) + 1) % order.length];
        applyDensity(next, true);
        showToast(`界面密度已切换为：${next === "compact" ? "紧凑" : next === "spacious" ? "舒适" : "标准"}`, "success");
      },
    },
  );
  return items;
}

function renderCommandResults(query = "") {
  const host = document.getElementById("cmdResults");
  if (!host) return;
  const q = query.trim().toLowerCase();
  const all = buildCommandItems();
  cmdFilteredItems = q ? all.filter((item) => item.keywords.includes(q)) : all.slice(0, 26);
  cmdSelectedIndex = Math.min(cmdSelectedIndex, Math.max(cmdFilteredItems.length - 1, 0));

  if (!cmdFilteredItems.length) {
    host.innerHTML = '<div class="empty-state">没有匹配的模块或操作</div>';
    return;
  }

  let html = "";
  let lastGroup = "";
  cmdFilteredItems.forEach((item, index) => {
    if (item.group !== lastGroup) {
      html += `<div class="cmd-group-title">${escapeHtml(item.group)}</div>`;
      lastGroup = item.group;
    }
    html += `
      <button type="button" class="cmd-item ${index === cmdSelectedIndex ? "selected" : ""}" data-cmd-index="${index}" role="option">
        <span class="cmd-item-left">
          <span class="nav-ico">${iconSvg(item.icon)}</span>
          <span><span class="cmd-item-title">${escapeHtml(item.title)}</span><span class="cmd-item-sub">${escapeHtml(item.subtitle)}</span></span>
        </span>
        <span class="cmd-item-tag">${escapeHtml(item.tag)}</span>
      </button>
    `;
  });
  host.innerHTML = html;
  host.querySelectorAll("[data-cmd-index]").forEach((btn) => {
    btn.addEventListener("click", () => executeCommandItem(Number(btn.dataset.cmdIndex)));
  });
}

function executeCommandItem(index) {
  const item = cmdFilteredItems[index];
  closeCommandPalette();
  if (item?.run) item.run();
}

function openCommandPalette() {
  const modal = document.getElementById("commandPalette");
  const input = document.getElementById("cmdSearchInput");
  if (!modal || !input) return;
  modal.classList.remove("hidden");
  input.value = "";
  cmdSelectedIndex = 0;
  renderCommandResults("");
  window.requestAnimationFrame(() => input.focus());
}

function closeCommandPalette() {
  const modal = document.getElementById("commandPalette");
  if (modal) modal.classList.add("hidden");
}

function toggleCommandPalette() {
  const modal = document.getElementById("commandPalette");
  if (!modal) return;
  if (modal.classList.contains("hidden")) openCommandPalette();
  else closeCommandPalette();
}

async function copyTextWithFeedback(text, label = "") {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    showToast(label || `已复制：${text}`, "success");
  } catch (_e) {
    showToast("复制失败，请手动选中复制", "error");
  }
}

function initWorkspaceEnhancements() {
  // Density controls
  applyDensity(document.documentElement.dataset.density || "comfortable", false);
  document.querySelectorAll("[data-density-option]").forEach((btn) => {
    btn.addEventListener("click", () => applyDensity(btn.dataset.densityOption, true));
  });

  // Sidebar rail & mobile drawer
  document.getElementById("sidebarToggle")?.addEventListener("click", toggleSidebarRail);
  document.getElementById("mobileNavToggle")?.addEventListener("click", () => {
    document.body.classList.toggle("mobile-nav-open");
  });
  document.getElementById("sidebarBackdrop")?.addEventListener("click", closeMobileNav);

  // Command palette
  document.getElementById("openCommandPalette")?.addEventListener("click", openCommandPalette);
  document.getElementById("topbarSearchBtn")?.addEventListener("click", openCommandPalette);
  document.querySelectorAll("[data-close-cmd]").forEach((el) => el.addEventListener("click", closeCommandPalette));
  const cmdInput = document.getElementById("cmdSearchInput");
  if (cmdInput) {
    cmdInput.addEventListener("input", () => {
      cmdSelectedIndex = 0;
      renderCommandResults(cmdInput.value);
    });
    cmdInput.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        cmdSelectedIndex = (cmdSelectedIndex + 1) % Math.max(cmdFilteredItems.length, 1);
        renderCommandResults(cmdInput.value);
        document.querySelector("#cmdResults .cmd-item.selected")?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        cmdSelectedIndex = (cmdSelectedIndex - 1 + Math.max(cmdFilteredItems.length, 1)) % Math.max(cmdFilteredItems.length, 1);
        renderCommandResults(cmdInput.value);
        document.querySelector("#cmdResults .cmd-item.selected")?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (cmdFilteredItems.length) executeCommandItem(cmdSelectedIndex);
      }
    });
  }

  // Clickable view jumps (Dashboard KPI tiles, quick links)
  document.querySelectorAll("[data-jump-view]").forEach((el) => {
    const jump = () => showView(el.dataset.jumpView);
    el.addEventListener("click", jump);
    if (el.getAttribute("role") === "button") {
      el.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          jump();
        }
      });
    }
  });

  // Module Hub filters
  document.querySelectorAll("#moduleCategoryFilter [data-module-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.moduleCategoryFilter = btn.dataset.moduleCat || "all";
      document.querySelectorAll("#moduleCategoryFilter [data-module-cat]").forEach((b) => b.classList.toggle("active", b === btn));
      renderModuleCards();
    });
  });
  document.querySelectorAll("#moduleStatusFilter [data-module-state]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.moduleStatusFilter = btn.dataset.moduleState || "all";
      document.querySelectorAll("#moduleStatusFilter [data-module-state]").forEach((b) => b.classList.toggle("active", b === btn));
      renderModuleCards();
    });
  });
  document.getElementById("moduleSearchInput")?.addEventListener("input", (event) => {
    state.moduleSearchQuery = event.target.value || "";
    renderModuleCards();
  });

  // Heavy-module Sub-tabs
  document.querySelectorAll(".subtab-bar[data-tab-group]").forEach((bar) => {
    const group = bar.dataset.tabGroup;
    bar.querySelectorAll(".subtab-btn[data-tab-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tabTarget;
        bar.querySelectorAll(".subtab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        document.querySelectorAll(`.tab-pane[data-tab-group="${group}"]`).forEach((pane) => {
          pane.classList.toggle("active", pane.dataset.tabPane === target);
        });
      });
    });
  });

  // Inline module banner switches
  document.querySelectorAll("[data-module-toggle]").forEach((input) => {
    input.addEventListener("change", async (event) => {
      const moduleId = input.dataset.moduleToggle;
      const targetChecked = event.target.checked;
      input.disabled = true;
      try {
        await toggleModuleEnabled(moduleId, targetChecked);
        showToast(targetChecked ? "模块已启用并实时生效" : "模块已停用并实时生效", "success");
      } catch (error) {
        event.target.checked = !targetChecked;
        showToast(`切换模块状态失败：${error.message}`, "error");
      } finally {
        input.disabled = false;
      }
    });
  });

  // Copyable command tags
  document.addEventListener("click", (event) => {
    const chip = event.target.closest(".copy-cmd[data-copy]");
    if (!chip) return;
    void copyTextWithFeedback(chip.dataset.copy, `已复制指令：${chip.dataset.copy}`);
  });

  // Muvyo-style Log Center controls: tabs, level select, search, auto-scroll, wrap, download, clear, copy
  document.querySelectorAll("[data-log-tab]").forEach((tab) => {
    tab.addEventListener("click", () => void switchLogTab(tab.dataset.logTab));
  });
  document.getElementById("logLevelSelect")?.addEventListener("change", (event) => {
    state.logLevelFilter = event.target.value || "ALL";
    renderLogOutput();
  });
  document.getElementById("logSearchInput")?.addEventListener("input", (event) => {
    state.logSearchQuery = event.target.value || "";
    renderLogOutput();
  });
  document.getElementById("toggleLogAutoScrollBtn")?.addEventListener("click", () => {
    state.logAutoScroll = !state.logAutoScroll;
    syncLogToolbarUI();
    if (state.logAutoScroll) scrollLogsToBottom(true);
  });
  document.getElementById("logScrollBottomBtn")?.addEventListener("click", () => {
    state.logAutoScroll = true;
    syncLogToolbarUI();
    scrollLogsToBottom(true);
  });
  document.getElementById("liveLogs")?.addEventListener("scroll", (event) => {
    if (logProgrammaticScroll) return;
    const box = event.currentTarget;
    const distFromBottom = box.scrollHeight - (box.scrollTop + box.clientHeight);
    const bottomBtn = document.getElementById("logScrollBottomBtn");
    if (distFromBottom > 42) {
      if (state.logAutoScroll && !state.logsViewingFile) {
        state.logAutoScroll = false;
        syncLogToolbarUI();
      }
      bottomBtn?.classList.remove("hidden");
    } else if (distFromBottom <= 16) {
      bottomBtn?.classList.add("hidden");
    }
  });
  document.getElementById("toggleLogWrapBtn")?.addEventListener("click", () => {
    state.logWordWrap = !state.logWordWrap;
    syncLogToolbarUI();
  });
  document.getElementById("downloadActiveLogBtn")?.addEventListener("click", () => {
    const fileName =
      (state.logsViewingFile && state.activeLogFile) ||
      state.status?.logs?.file_name ||
      state.logFilesList?.[0]?.name ||
      "";
    if (fileName) {
      const a = document.createElement("a");
      a.href = `/api/logs/download?file=${encodeURIComponent(fileName)}`;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      return;
    }
    const text = document.getElementById("liveLogs")?.innerText || "";
    if (!text.trim()) {
      showToast("当前没有可下载的日志内容", "error");
      return;
    }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "telegrambot.log";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.getElementById("clearLogsBtn")?.addEventListener("click", () => {
    if (state.logsViewingFile) {
      state.logFileContent = "";
    } else if (state.recentLogRecords.length) {
      state.logClearedCursor = logRecordKey(state.recentLogRecords[state.recentLogRecords.length - 1]);
    }
    renderLogOutput();
    showToast("已清空当前日志视图（不影响服务端日志文件）", "success");
  });
  document.getElementById("copyLogsBtn")?.addEventListener("click", () => {
    const text = document.getElementById("liveLogs")?.innerText || "";
    if (!text.trim()) {
      showToast("当前没有可复制的日志内容", "error");
      return;
    }
    void copyTextWithFeedback(text, "已复制当前日志到剪贴板");
  });
  syncLogToolbarUI();

  // Settings group search
  document.getElementById("groupSearchInput")?.addEventListener("input", (event) => {
    state.groupSearchQuery = event.target.value || "";
    applyGroupSearchFilter();
  });

  // Dirty form tracking & floating save bar
  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!target || target.type === "search" || target.closest("#commandPalette")) return;
    if (target.closest("[data-module-toggle]") || target.id === "logRefreshInterval" || target.id === "autoRefreshLogs" || target.id === "usageRange") return;
    const view = target.closest(".view");
    if (view && (view.dataset.saveBtn || view.id === "moduleRedPacket")) {
      markViewDirty(view.id);
    }
  });
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || target.type === "search" || target.closest("#commandPalette")) return;
    if (target.hasAttribute("data-module-toggle") || target.id === "autoRefreshLogs" || target.id === "usageRange") return;
    const view = target.closest(".view");
    if (view && (view.dataset.saveBtn || view.id === "moduleRedPacket")) {
      markViewDirty(view.id);
    }
  });

  document.getElementById("dirtySaveBtn")?.addEventListener("click", () => {
    const activeView = document.querySelector(".view.active");
    const saveId = activeView?.id === "moduleRedPacket" ? "saveRedPacketTemplates" : activeView?.dataset?.saveBtn;
    if (saveId) document.getElementById(saveId)?.click();
  });

  document.getElementById("dirtyDiscardBtn")?.addEventListener("click", () => {
    const activeId = state.currentView;
    if (!activeId) return;
    clearViewDirty(activeId);
    prepareView(activeId);
    if (activeId === "settings") void refreshSettings();
    showToast("已恢复到已保存的配置", "success");
  });

  // High-DPI responsive charts via ResizeObserver
  if (typeof ResizeObserver !== "undefined") {
    let obsTimer = null;
    const ro = new ResizeObserver(() => {
      if (obsTimer) window.clearTimeout(obsTimer);
      obsTimer = window.setTimeout(() => {
        drawCharts();
        if (state.lastUsageData) renderUsage(state.lastUsageData);
      }, 80);
    });
    document.querySelectorAll(".chart-stage").forEach((el) => ro.observe(el));
  }

  // Auth status & logout button
  void getJson("/api/auth")
    .then((auth) => {
      const logoutBtn = document.getElementById("logoutBtn");
      if (logoutBtn && auth?.auth_enabled) {
        logoutBtn.classList.remove("hidden");
        logoutBtn.addEventListener("click", async () => {
          try {
            await postJson("/api/logout", {});
          } finally {
            window.location.assign("/login");
          }
        });
      }
    })
    .catch(() => {});

  initModuleTransfer();
}

const MODULE_TRANSFER_CATEGORY_ORDER = ["interactive", "ai", "media", "sync"];

function initModuleTransfer() {
  const exportDialog = document.getElementById("moduleExportDialog");
  const importDialog = document.getElementById("moduleImportDialog");
  if (!exportDialog || !importDialog) return;

  const exportList = document.getElementById("moduleExportList");
  const exportSummary = document.getElementById("moduleExportSummary");
  const exportConfirmBtn = document.getElementById("confirmModuleExportBtn");

  const importFileInput = document.getElementById("moduleImportFileInput");
  const importDropzone = document.getElementById("moduleImportDropzone");
  const importFileLabel = document.getElementById("moduleImportFileLabel");
  const importFileMeta = document.getElementById("moduleImportFileMeta");
  const importPreview = document.getElementById("moduleImportPreview");
  const importList = document.getElementById("moduleImportList");
  const importSummary = document.getElementById("moduleImportSummary");
  const importApplyEnabled = document.getElementById("moduleImportApplyEnabled");
  const importError = document.getElementById("moduleImportError");
  const importConfirmBtn = document.getElementById("confirmModuleImportBtn");

  const transferState = {
    importPayload: null,
    importMatchedIds: [],
  };

  function closeDialog(kind) {
    const dlg = kind === "export" ? exportDialog : importDialog;
    dlg.classList.add("hidden");
    document.body.classList.remove("modal-open");
  }

  function renderTransferGroups(container, items, checkboxName) {
    const byCat = new Map();
    MODULE_TRANSFER_CATEGORY_ORDER.forEach((cat) => byCat.set(cat, []));
    items.forEach((item) => {
      const cat = MODULE_CATEGORY_KEYS[item.id] || "sync";
      if (!byCat.has(cat)) byCat.set(cat, []);
      byCat.get(cat).push(item);
    });
    const html = [];
    byCat.forEach((list, cat) => {
      if (!list.length) return;
      const catLabel = CATEGORY_LABELS[cat] || "其他模块";
      html.push(`
        <div class="transfer-group">
          <div class="transfer-group-head">${escapeHtml(catLabel)}</div>
          <div class="transfer-grid">
            ${list.map((item) => `
              <label class="transfer-item">
                <input type="checkbox" name="${checkboxName}" value="${escapeAttr(item.id)}" ${item.checked ? "checked" : ""} />
                <span class="transfer-item-ico">${iconSvg(moduleIcon(item.id))}</span>
                <span class="transfer-item-copy">
                  <strong>${escapeHtml(item.name)}</strong>
                  <small>${escapeHtml(item.meta || "")}</small>
                </span>
                <span class="tag ${item.badgeClass || ""}">${escapeHtml(item.badgeText || "")}</span>
              </label>
            `).join("")}
          </div>
        </div>
      `);
    });
    container.innerHTML = html.join("");
  }

  function selectedIdsIn(container) {
    return Array.from(container.querySelectorAll('input[type="checkbox"]:checked')).map((el) => el.value);
  }

  function updateExportSelectionState() {
    const total = exportList.querySelectorAll('input[type="checkbox"]').length;
    const count = selectedIdsIn(exportList).length;
    exportSummary.textContent = `已选 ${count} / ${total} 个模块`;
    exportConfirmBtn.disabled = count === 0;
  }

  function updateImportSelectionState() {
    const total = importList.querySelectorAll('input[type="checkbox"]').length;
    const count = selectedIdsIn(importList).length;
    importSummary.textContent = `已选 ${count} / ${total} 个模块`;
    importConfirmBtn.disabled = !transferState.importPayload || count === 0;
  }

  function openExportDialog() {
    const modules = Array.isArray(state.modules) ? state.modules : [];
    const items = modules.map((mod) => ({
      id: mod.id,
      name: mod.name || mod.id,
      meta: mod.id,
      checked: true,
      badgeText: mod.enabled ? "已启用" : "未启用",
      badgeClass: mod.enabled ? "enabled" : "disabled",
    }));
    renderTransferGroups(exportList, items, "export_module");
    updateExportSelectionState();
    exportDialog.classList.remove("hidden");
  }

  function resetImportDialog() {
    transferState.importPayload = null;
    transferState.importMatchedIds = [];
    importFileInput.value = "";
    importFileLabel.textContent = "点击选择或拖入功能模块配置 JSON 文件";
    importFileMeta.textContent = "仅读取功能模块配置，任何非模块配置项都会自动忽略";
    importPreview.classList.add("hidden");
    importList.innerHTML = "";
    importError.textContent = "";
    importError.classList.add("hidden");
    importApplyEnabled.checked = true;
    importConfirmBtn.disabled = true;
  }

  function showImportError(message) {
    transferState.importPayload = null;
    transferState.importMatchedIds = [];
    importPreview.classList.add("hidden");
    importError.textContent = message;
    importError.classList.remove("hidden");
    importConfirmBtn.disabled = true;
  }

  function handleImportFile(file) {
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      showImportError("文件体积超过 4 MB 限制，请选择有效的功能模块配置 JSON 文件。");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || ""));
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          showImportError("文件内容不是合法的 JSON 对象。");
          return;
        }
        if (parsed.format && parsed.format !== "telebot-modules-config") {
          showImportError("不支持的配置文件格式，请选择通过“导出配置”生成的 JSON 文件。");
          return;
        }
        const rawModules = parsed.modules;
        if (!rawModules || typeof rawModules !== "object" || Array.isArray(rawModules)) {
          showImportError("配置文件缺少有效的 modules 字段。");
          return;
        }
        const registeredById = new Map((state.modules || []).map((mod) => [mod.id, mod]));
        const matched = [];
        const ignoredKeys = [];
        Object.entries(rawModules).forEach(([id, entry]) => {
          const registered = registeredById.get(id);
          if (!registered || !entry || typeof entry !== "object") {
            ignoredKeys.push(id);
            return;
          }
          const hasEnabled = typeof entry.enabled === "boolean";
          matched.push({
            id,
            name: registered.name || entry.name || id,
            meta: hasEnabled
              ? `当前${registered.enabled ? "已启用" : "未启用"} → 导入${entry.enabled ? "启用" : "停用"}`
              : `当前${registered.enabled ? "已启用" : "未启用"}`,
            checked: true,
            badgeText: hasEnabled ? (entry.enabled ? "启用" : "停用") : "仅参数",
            badgeClass: hasEnabled ? (entry.enabled ? "enabled" : "disabled") : "",
          });
        });
        if (!matched.length) {
          showImportError("文件中未包含任何当前支持的功能模块配置。");
          return;
        }
        transferState.importPayload = parsed;
        transferState.importMatchedIds = matched.map((item) => item.id);
        importFileLabel.textContent = file.name;
        const metaParts = [`识别 ${matched.length} 个功能模块`];
        if (parsed.exported_at) metaParts.push(`导出于 ${String(parsed.exported_at).replace("T", " ")}`);
        if (ignoredKeys.length) metaParts.push(`已自动忽略 ${ignoredKeys.length} 项非模块/不支持键`);
        importFileMeta.textContent = metaParts.join(" · ");
        importError.classList.add("hidden");
        renderTransferGroups(importList, matched, "import_module");
        importPreview.classList.remove("hidden");
        updateImportSelectionState();
      } catch (err) {
        showImportError(`JSON 解析失败：${err.message}`);
      }
    };
    reader.onerror = () => showImportError("读取文件失败，请重试。");
    reader.readAsText(file, "utf-8");
  }

  document.getElementById("openModuleExportBtn")?.addEventListener("click", openExportDialog);
  document.getElementById("openModuleImportBtn")?.addEventListener("click", () => {
    resetImportDialog();
    importDialog.classList.remove("hidden");
  });

  document.querySelectorAll("[data-close-transfer]").forEach((el) => {
    el.addEventListener("click", () => closeDialog(el.dataset.closeTransfer));
  });

  exportList.addEventListener("change", updateExportSelectionState);
  importList.addEventListener("change", updateImportSelectionState);

  document.getElementById("moduleExportSelectAll")?.addEventListener("click", () => {
    exportList.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = true; });
    updateExportSelectionState();
  });
  document.getElementById("moduleExportSelectEnabled")?.addEventListener("click", () => {
    const enabledSet = new Set((state.modules || []).filter((m) => m.enabled).map((m) => m.id));
    exportList.querySelectorAll('input[type="checkbox"]').forEach((el) => {
      el.checked = enabledSet.has(el.value);
    });
    updateExportSelectionState();
  });
  document.getElementById("moduleExportSelectNone")?.addEventListener("click", () => {
    exportList.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = false; });
    updateExportSelectionState();
  });

  document.getElementById("moduleImportSelectAll")?.addEventListener("click", () => {
    importList.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = true; });
    updateImportSelectionState();
  });
  document.getElementById("moduleImportSelectNone")?.addEventListener("click", () => {
    importList.querySelectorAll('input[type="checkbox"]').forEach((el) => { el.checked = false; });
    updateImportSelectionState();
  });

  const triggerPick = () => importFileInput.click();
  document.getElementById("moduleImportPickBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    triggerPick();
  });
  importDropzone?.addEventListener("click", triggerPick);
  importDropzone?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      triggerPick();
    }
  });
  importDropzone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    importDropzone.classList.add("is-dragover");
  });
  importDropzone?.addEventListener("dragleave", () => {
    importDropzone.classList.remove("is-dragover");
  });
  importDropzone?.addEventListener("drop", (event) => {
    event.preventDefault();
    importDropzone.classList.remove("is-dragover");
    const file = event.dataTransfer?.files?.[0];
    if (file) handleImportFile(file);
  });
  importFileInput?.addEventListener("change", () => {
    const file = importFileInput.files?.[0];
    if (file) handleImportFile(file);
  });

  exportConfirmBtn?.addEventListener("click", async () => {
    const selected = selectedIdsIn(exportList);
    if (!selected.length) return;
    exportConfirmBtn.disabled = true;
    try {
      const result = await postJson("/api/modules/export", { modules: selected });
      const bundle = result.export || result;
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
      const blob = new Blob([JSON.stringify(bundle, null, 2) + "\n"], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `telebot-modules-${stamp}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      closeDialog("export");
      showToast(`已导出 ${selected.length} 个功能模块配置`, "success");
    } catch (error) {
      showToast(`导出失败：${error.message}`, "error");
    } finally {
      updateExportSelectionState();
    }
  });

  importConfirmBtn?.addEventListener("click", async () => {
    const selected = selectedIdsIn(importList);
    if (!transferState.importPayload || !selected.length) return;
    importConfirmBtn.disabled = true;
    try {
      const result = await postJson("/api/modules/import", {
        data: transferState.importPayload,
        modules: selected,
        apply_enabled: Boolean(importApplyEnabled.checked),
      });
      if (Array.isArray(result.modules)) {
        state.modules = result.modules;
        updateModulesOverview(state.modules);
        renderModuleCards();
      }
      await Promise.allSettled([refreshModules(), refreshAi(), refreshStatus()]);
      closeDialog("import");
      const importedCount = Array.isArray(result.imported) ? result.imported.length : selected.length;
      showToast(`已导入 ${importedCount} 个功能模块配置（系统配置与 AI 服务未改动）`, "success");
    } catch (error) {
      showImportError(`导入失败：${error.message}`);
    } finally {
      updateImportSelectionState();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!exportDialog.classList.contains("hidden")) closeDialog("export");
    if (!importDialog.classList.contains("hidden")) closeDialog("import");
  });
}

initWorkspaceEnhancements();
loadMetricHistory();
refreshAll().catch((error) => showToast(`初始化加载失败：${error.message}`, "error"));
scheduleStatusLoop();
scheduleLogRefreshLoop();
