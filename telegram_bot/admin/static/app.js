const GROUP_NAME_CACHE_KEY = "telegrambot.settings.groupNameCache.v1";

const state = {
  status: null,
  settings: null,
  groups: [],
  checkinTargets: [],
  modules: [],
  metricHistory: [],
  chartWindow: "15m",
  logAutoRefresh: true,
  logRefreshIntervalSeconds: 1,
  logsViewingFile: false,
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
  magnet_import: '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M7 4h3v7a2 2 0 0 0 4 0V4h3"/><path d="M12 17v4"/><path d="m9 19 3 3 3-3"/>',
  quote: '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-4 4z"/><path d="M8.5 9.5h2v3h-2zM13.5 9.5h2v3h-2z"/>',
  chat_games: '<path d="M7 9h10a4 4 0 0 1 3.8 5.3l-.7 2.1a2.2 2.2 0 0 1-3.7.8L14.8 16H9.2l-1.6 1.2a2.2 2.2 0 0 1-3.7-.8l-.7-2.1A4 4 0 0 1 7 9z"/><path d="M8 12v3M6.5 13.5h3M15.5 12.5h.01M18 14.5h.01"/>',
  aiServices: '<path d="M12 4v4M12 16v4M4 12h4M16 12h4"/><circle cx="12" cy="12" r="4"/><path d="M6.5 6.5 9 9M15 15l2.5 2.5M17.5 6.5 15 9M9 15l-2.5 2.5"/>',
  aiUsage: '<path d="M5 19V5"/><path d="M5 19h15"/><path d="M8 15l3-4 3 2 4-6"/><circle cx="11" cy="11" r="1.5"/><circle cx="18" cy="7" r="1.5"/>',
  logs: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4"/>',
  chevronUp: '<path d="m6 15 6-6 6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
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
  moduleQuote: "quote",
  moduleChatGames: "chat_games",
  aiServices: "aiServices",
  aiUsage: "aiUsage",
  logs: "logs",
  settings: "settings",
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
  moduleQuote: ["语录贴纸", "回复消息 · 生成语录贴纸"],
  moduleChatGames: ["聊天小游戏", "幸运词 · Emoji 图谜 · 乱码解码"],
  aiServices: ["AI 服务配置", "连接服务 · 提供商类型和模型"],
  aiUsage: ["AI 用量统计", "Token 消耗 · 模型和功能分布"],
  logs: ["日志", "实时日志 · 历史备份"],
  settings: ["系统设置", "Telegram 群组监听"],
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
  quote: "moduleQuote",
  chat_games: "moduleChatGames",
};

document.querySelectorAll(".nav-item, .sub-nav-item").forEach((button) => {
  button.addEventListener("click", (event) => {
    const group = button.closest(".nav-group");
    const isMobileNav = window.matchMedia("(max-width: 920px)").matches;
    if (button.classList.contains("nav-parent") && group && isMobileNav && group.classList.contains("active") && group.classList.contains("expanded")) {
      setGroupExpanded(group, false);
      return;
    }
    if (button.classList.contains("nav-parent") && event.target.closest(".chevron")) {
      setGroupExpanded(group, !group.classList.contains("expanded"));
      return;
    }
    const isSubNavItem = button.classList.contains("sub-nav-item");
    if (group) setGroupExpanded(group, true);
    showView(button.dataset.view);
    if (isMobileNav && isSubNavItem && group) setGroupExpanded(group, false);
  });
});

document.querySelectorAll("[data-service-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    closeServiceMenu();
    await postJson(`/api/service/${button.dataset.serviceAction}`, {});
    await refreshAll();
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
  if (event.key === "Escape") closeServiceMenu();
});

document.getElementById("refreshLogs").addEventListener("click", refreshLogs);
document.getElementById("autoRefreshLogs").addEventListener("change", (event) => {
  state.logAutoRefresh = event.target.checked;
  state.logsViewingFile = false;
  updateLogRefreshState();
  scheduleLogRefreshLoop();
  if (state.logAutoRefresh) refreshLogs();
});
const logRefreshIntervalInput = document.getElementById("logRefreshInterval");
if (logRefreshIntervalInput) {
  logRefreshIntervalInput.value = formatRefreshInterval(state.logRefreshIntervalSeconds);
  logRefreshIntervalInput.addEventListener("input", handleLogRefreshIntervalChange);
  logRefreshIntervalInput.addEventListener("change", handleLogRefreshIntervalChange);
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

function showView(viewId) {
  const view = document.getElementById(viewId);
  if (!view) return;

  prepareView(viewId);
  document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
  view.classList.add("active");

  document.querySelectorAll(".nav-item, .sub-nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });
  document.querySelectorAll(".nav-group").forEach((group) => {
    const ownsView = Boolean(group.querySelector(`[data-view="${viewId}"]`));
    group.classList.toggle("active", ownsView);
    if (ownsView) setGroupExpanded(group, true);
    if (!ownsView && window.matchMedia("(max-width: 920px)").matches) setGroupExpanded(group, false);
  });

  const title = titles[viewId] || titles.dashboard;
  document.getElementById("pageTitle").textContent = title[0];
  document.getElementById("pageSubtitle").textContent = title[1];
  const pageIcon = document.getElementById("pageIcon");
  if (pageIcon) pageIcon.innerHTML = iconSvg(viewIconMap[viewId] || "dashboard");
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
  if (viewId === "moduleQuote") {
    const module = findModule("quote");
    if (module) fillQuoteSettings(module);
  }
  if (viewId === "moduleChatGames") {
    const module = findModule("chat_games");
    if (module) fillChatGamesSettings(module);
  }
  if (viewId === "logs") {
    state.logsViewingFile = false;
    updateLogRefreshState();
    refreshLogs();
  }
  if (viewId === "aiUsage") refreshAiUsage();
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

  renderDevice(data);
  renderHardware(data);
  renderStats(data);
  drawCharts();
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
  addKv(list, "硬盘容量", `${hardware.disk_percent}%`);
  document.getElementById("diskMeter").style.width = `${Math.min(hardware.disk_percent, 100)}%`;
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
  const container = document.getElementById("moduleCards");
  container.innerHTML = "";
  state.modules.forEach((module) => {
    const card = document.createElement("article");
    card.className = "module-card";
    card.tabIndex = 0;
    card.role = "button";
    card.dataset.moduleId = module.id;
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
      <div class="tag-row">
        <span class="tag ${module.enabled ? "enabled" : "disabled"}">${module.enabled ? "已启用" : "未启用"}</span>
        <span class="tag">${escapeHtml(module.status)}</span>
        <span class="tag">${escapeHtml(module.category)}</span>
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
      await toggleModuleEnabled(module.id, event.target.checked);
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
  if (module.id === "red_packet") showRedPacketDetail(module);
  if (module.id === "checkin") showCheckinSettings(module);
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
    <div class="panel-head">
      <div>
        <h2>${escapeHtml(module.name)}</h2>
        <p class="hint">按钮模板首次点击不等待；开启“首次抢后自动发言”后：立即点击 → 随机发言 → 可选延迟 → 再次点击。未开启时延迟不生效。</p>
      </div>
      <div class="module-actions">
        <button id="toggleModule" class="${module.enabled ? "" : "primary"}">${module.enabled ? "禁用" : "启用"}</button>
        <button id="addRedPacketTemplate">新增模板</button>
        <button id="saveRedPacketTemplates" class="primary">保存模板</button>
      </div>
    </div>
    <div class="red-packet-summary">
      <span class="tag">${module.enabled ? "模块已启用" : "模块未启用"}</span>
      <span class="tag">模板 ${templates.length} 个</span>
      <span class="tag">图片识别已停用</span>
      <span class="tag">ID 去重 48 小时</span>
      <span id="redPacketSaveState" class="hint">${escapeHtml(notice)}</span>
    </div>
    <div class="red-packet-settings setting-form" aria-label="抢红包发送设置">
      <label>
        <span>发送延迟</span>
        <span class="red-packet-delay-control">
          <input id="redPacketSendDelayMs" type="number" min="0" max="60000" step="100" value="${sendDelayMs}" aria-label="发送延迟（毫秒）">
          <small>ms</small>
        </span>
      </label>
      <label>
        <span>自动发言候选</span>
        <span class="red-packet-message-control">
          <textarea id="redPacketPreClickMessages" rows="4" aria-describedby="redPacketPreClickMessagesHint" placeholder="手气不错&#10;感谢老板">${escapeHtml(preClickMessages.join("\n"))}</textarea>
          <small id="redPacketPreClickMessagesHint" class="hint">每行一条，首次点击后随机发送；开启延迟时，等待后再次点击。消息中的逗号会原样保留。</small>
        </span>
      </label>
    </div>
    <div id="redPacketTemplates" class="template-list"></div>
  `;
  const list = document.getElementById("redPacketTemplates");
  templates.forEach((template) => list.appendChild(redPacketTemplateForm(template)));
  if (!templates.length) {
    list.innerHTML = '<div class="empty-state">还没有模板。点击“新增模板”创建第一个红包或抽奖规则。</div>';
  }
  document.getElementById("toggleModule").addEventListener("click", async () => {
    const result = await putJson(`/api/modules/${module.id}`, { enabled: !module.enabled });
    await refreshModules();
    showRedPacketDetail(result.module, result.module.enabled ? "模块已启用并实时生效" : "模块已禁用并实时生效");
  });
  document.getElementById("addRedPacketTemplate").addEventListener("click", () => {
    const empty = list.querySelector(".empty-state");
    if (empty) empty.remove();
    list.appendChild(redPacketTemplateForm(newRedPacketTemplate()));
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
  list.appendChild(sendRedPacketTemplateForm(newSendRedPacketTemplate()));
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
  document.getElementById("replyKeyState").textContent = data.providers.reply.has_api_key ? "已配置 Key" : "未配置 Key";
  document.getElementById("imageKeyState").textContent = data.providers.image.has_api_key ? "已配置 Key" : "未配置 Key";
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
  document.querySelectorAll("[data-secret-input]").forEach((input) => {
    input.addEventListener("focus", () => {
      input.type = "text";
    });
    input.addEventListener("blur", () => {
      if (input.dataset.pinned !== "true") input.type = "password";
    });
  });
  document.querySelectorAll("[data-secret-toggle]").forEach((button) => {
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => {
      const input = button.closest(".secret-input")?.querySelector("[data-secret-input]");
      if (!input) return;
      const visible = input.dataset.pinned === "true";
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
  document.getElementById("aiServiceSaveState").textContent = result ? "已保存，后续 AI 请求会使用新的服务连接信息。" : "保存失败";
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
  list.appendChild(decryptTemplateForm(newDecryptTemplate()));
}

function decryptTemplateForm(template) {
  const card = document.createElement("section");
  card.className = "template-card";
  card.dataset.templateId = template.id || `decrypt_${Date.now()}`;
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
      trigger_keywords: splitLines(card.querySelector('[data-field="trigger_keywords"]').value),
      id_markers: splitLines(card.querySelector('[data-field="id_markers"]').value),
      prompt: "",
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
    ignore_command_prefixes: splitLines(form.elements.ignore_command_prefixes.value),
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
    command_prefixes: splitLines(form.elements.command_prefixes.value),
    copy_text_command_prefixes: splitLines(form.elements.copy_text_command_prefixes.value),
    quote_command_prefixes: splitLines(form.elements.quote_command_prefixes.value),
    link_command_prefixes: splitLines(form.elements.link_command_prefixes.value),
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
  list.appendChild(checkinTaskForm(newCheckinTask()));
  document.getElementById("checkinTaskCount").textContent = `签到 ${list.querySelectorAll(".template-card").length} 个`;
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
  const range = document.getElementById("usageRange").value;
  const data = await getJson(`/api/ai/usage?range=${encodeURIComponent(range)}`);
  renderUsage(data);
}

function renderUsage(data) {
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
      color: "#817b73",
      fill: "rgba(129, 123, 115, 0.16)",
      values: requestSeries,
    },
    {
      key: "tokens",
      label: "Token 总数",
      value: compactNumber(summary.total_tokens),
      sub: `输入 ${compactNumber(summary.input_tokens)} / 输出 ${compactNumber(summary.output_tokens)}`,
      color: "#865dff",
      fill: "rgba(134, 93, 255, 0.18)",
      values: tokenSeries,
    },
    {
      key: "rpm",
      label: "RPM",
      value: Number(summary.rpm || 0).toFixed(2),
      sub: `请求总数 ${formatNumber(summary.requests)} · 平均耗时 ${formatMs(summary.avg_latency_ms)}`,
      color: "#20bf65",
      fill: "rgba(32, 191, 101, 0.18)",
      values: requestSeries,
    },
    {
      key: "tpm",
      label: "TPM",
      value: formatUsageRate(summary.tpm),
      sub: `Token 总数 ${compactNumber(summary.total_tokens)}`,
      color: "#ff6b17",
      fill: "rgba(255, 107, 23, 0.18)",
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
          <canvas id="usageSpark-${item.key}" class="usage-sparkline" height="74"></canvas>
        </article>
      `,
    )
    .join("");
  kpis.forEach((item) => {
    drawUsageSparkline(`usageSpark-${item.key}`, item.values, item.color, item.fill);
  });
  renderUsageRows("usageModelRows", data.models || [], "model");
  renderUsageRows("usageFeatureRows", data.features || [], "feature");
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

function drawUsageSparkline(canvasId, values, color, fill) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const normalized = values.length ? values : [0];
  drawLineChart(canvas, [{ values: normalized, color, fill }], Math.max(...normalized, 1));
}

async function refreshLogs() {
  state.logsViewingFile = false;
  await refreshRecentLogs();
  await refreshLogFiles();
  updateLogRefreshState();
}

async function refreshRecentLogs() {
  const recent = await getJson("/api/logs/recent");
  const box = document.getElementById("liveLogs");
  const stickToBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
  box.textContent = recent.records
    .map((record) => `${record.time} ${record.level} [${record.name}] ${record.message}`)
    .join("\n");
  if (stickToBottom) box.scrollTop = box.scrollHeight;
}

async function refreshLogFiles() {
  const files = await getJson("/api/logs/files");
  const fileList = document.getElementById("logFiles");
  fileList.innerHTML = "";
  files.files.forEach((file) => {
    const row = document.createElement("div");
    row.className = "file-row";
    row.innerHTML = `
      <strong>${escapeHtml(file.name)}</strong>
      <p>${formatBytes(file.size)}</p>
      <button data-file="${escapeHtml(file.name)}">查看</button>
      <a href="/api/logs/download?file=${encodeURIComponent(file.name)}">下载</a>
    `;
    row.querySelector("button").addEventListener("click", () => readLogFile(file.name));
    fileList.appendChild(row);
  });
}

async function readLogFile(name) {
  const data = await getJson(`/api/logs/read?file=${encodeURIComponent(name)}&lines=400`);
  state.logsViewingFile = true;
  document.getElementById("liveLogs").textContent = data.content;
  updateLogRefreshState(`正在查看历史日志：${name}，手动刷新可回到实时日志`);
}

function updateLogRefreshState(message = "") {
  const label = document.getElementById("logRefreshState");
  if (!label) return;
  if (message) {
    label.textContent = message;
    return;
  }
  const intervalText = formatRefreshInterval(state.logRefreshIntervalSeconds);
  label.textContent = state.logAutoRefresh ? `实时日志每 ${intervalText} 秒刷新` : "自动刷新已关闭";
}

function handleLogRefreshIntervalChange(event) {
  const seconds = parseRefreshInterval(event.target.value);
  if (seconds === null) return;
  state.logRefreshIntervalSeconds = seconds;
  localStorage.setItem(LOG_REFRESH_INTERVAL_KEY, String(seconds));
  event.target.value = formatRefreshInterval(seconds);
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
  updateGroupCount();
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
    return;
  }
  groupIds.forEach((id) => {
    const meta = groupMetaForId(id);
    const chip = document.createElement("span");
    chip.className = "selected-group-chip";
    chip.innerHTML = `<span>${escapeHtml(meta.title || id)}</span><small>${escapeHtml(id)}</small>`;
    host.appendChild(chip);
  });
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

function drawCharts() {
  const history = visibleMetricHistory();
  const speedMax = Math.max(
    ...history.flatMap((item) => [item.downloadRate || 0, item.uploadRate || 0]),
    1024,
  );
  drawLineChart(document.getElementById("resourceChart"), [
    { values: history.map((item) => item.cpu), color: "#008ee8", fill: "rgba(0, 142, 232, 0.13)" },
    { values: history.map((item) => item.memory), color: "#9b38ff", fill: "rgba(155, 56, 255, 0.12)" },
  ], 100);
  drawLineChart(document.getElementById("speedChart"), [
    { values: history.map((item) => item.downloadRate || 0), color: "#008ee8", fill: "rgba(0, 142, 232, 0.11)" },
    { values: history.map((item) => item.uploadRate || 0), color: "#17b56b", fill: "rgba(23, 181, 107, 0.13)" },
  ], speedMax);
}

function drawLineChart(canvas, series, maxValue) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = rect.width || canvas.clientWidth || Number(canvas.getAttribute("width")) || 300;
  const height = rect.height || canvas.clientHeight || Number(canvas.getAttribute("height")) || 180;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(20, 32, 28, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  series.forEach((line) => {
    const values = line.values.length > 1 ? line.values : [line.values[0] || 0, line.values[0] || 0];
    const step = width / Math.max(values.length - 1, 1);
    ctx.beginPath();
    values.forEach((value, index) => {
      const x = index * step;
      const y = height - (Math.min(value, maxValue) / maxValue) * (height - 18) - 9;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = line.color;
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    ctx.fillStyle = line.fill;
    ctx.fill();
  });
}

async function getJson(url) {
  const response = await fetch(url);
  if (response.status === 401) redirectToLogin();
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
  if (response.status === 401) redirectToLogin();
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
  if (response.status === 401) redirectToLogin();
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${url} failed: ${response.status}`);
  return data;
}

function redirectToLogin() {
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

loadMetricHistory();
refreshAll();
setInterval(refreshStatus, 5000);
scheduleLogRefreshLoop();
