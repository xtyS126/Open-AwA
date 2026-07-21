/**
 * OpenAwA Cookie 助手 - popup 主逻辑
 *
 * 认证方式：API Key（OPENAWA_API_KEY）
 * 后端 get_current_user 路径 1 为 API Key 优先，匹配后直接返回 owner 用户，
 * 无需用户名密码登录。API Key 来自后端 .env.local 或环境变量。
 *
 * 功能：
 * 1. 配置 OpenAwA 后端地址（默认 127.0.0.1:8000）
 * 2. 保存 OpenAwA API Key（chrome.storage.local，仅扩展作用域可读）
 * 3. 获取当前浏览器中目标平台的 Cookie（chrome.cookies API）
 * 4. 将 B 站 Cookie 同步到后端 openbiliclaw-builtin 插件的 bilibili_cookie 字段
 *
 * 后端 API 约定：
 * - GET  /api/plugins                      获取插件列表（Bearer API Key 认证）
 * - GET  /api/plugins/{id}/config/export   获取插件当前配置（注意：非 /config，后者不存在）
 * - PUT  /api/plugins/{id}/config          保存插件配置（API Key 自动获得 owner/admin 权限）
 */

// ==================== 常量 ====================

const STORAGE_KEYS = {
  BACKEND: "openawa_backend_endpoint",
  API_KEY: "openawa_api_key",
};

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8000;
const MIN_API_KEY_LENGTH = 32;

// 平台 → Cookie 域名后缀映射
const PLATFORM_DOMAINS = {
  bilibili: [".bilibili.com"],
  x: [".x.com", ".twitter.com"],
  douyin: [".douyin.com"],
  xiaohongshu: [".xiaohongshu.com"],
  youtube: [".youtube.com"],
  zhihu: [".zhihu.com"],
  reddit: [".reddit.com", ".redd.it"],
};

// 平台 → 后端插件配置字段映射（所有平台均已支持同步）
const PLATFORM_CONFIG_FIELD = {
  bilibili: "bilibili_cookie",
  x: "x_cookie",
  douyin: "douyin_cookie",
  xiaohongshu: "xiaohongshu_cookie",
  youtube: "youtube_cookie",
  zhihu: "zhihu_cookie",
  reddit: "reddit_cookie",
};

// ==================== 状态 ====================

let state = {
  backendHost: DEFAULT_HOST,
  backendPort: DEFAULT_PORT,
  apiKey: null,
  pluginId: null, // openbiliclaw-builtin 插件 ID（缓存）
  currentPlatform: "bilibili",
  currentCookie: null, // { cookieString, length, domain, count }
};

// ==================== 工具函数 ====================

function $(id) {
  return document.getElementById(id);
}

function setStatus(elementId, message, type = "info") {
  const el = $(elementId);
  el.textContent = message;
  el.className = "status-line";
  if (type) el.classList.add(`status-${type}`);
}

function clearStatus(elementId) {
  const el = $(elementId);
  el.textContent = "";
  el.className = "status-line";
}

function setGlobalStatus(message, type = "info") {
  setStatus("global-status", message, type);
}

function getBackendOrigin() {
  return `http://${state.backendHost}:${state.backendPort}`;
}

function getBackendApiBase() {
  return `${getBackendOrigin()}/api`;
}

/**
 * 获取认证头。API Key 通过 Bearer 传递，后端路径 1 匹配后直接返回 owner。
 */
function getAuthHeaders() {
  const headers = {};
  if (state.apiKey) {
    headers["Authorization"] = `Bearer ${state.apiKey}`;
  }
  return headers;
}

/**
 * 掩码处理 Cookie 字符串，只显示前后各 20 字符。
 * 保护敏感信息，避免在 popup 预览中完整暴露。
 */
function maskCookie(cookieStr) {
  if (!cookieStr) return "";
  if (cookieStr.length <= 40) return cookieStr;
  return `${cookieStr.slice(0, 20)}...(${cookieStr.length - 40} 字符隐藏)...${cookieStr.slice(-20)}`;
}

/**
 * 掩码处理 API Key，只显示前 6 后 4 字符。
 */
function maskApiKey(key) {
  if (!key) return "";
  if (key.length <= 12) return "*".repeat(key.length);
  return `${key.slice(0, 6)}${"*".repeat(key.length - 10)}${key.slice(-4)}`;
}

// ==================== 存储读写 ====================

function storageGet(key) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(key, (items) => resolve(items?.[key]));
    } catch {
      resolve(undefined);
    }
  });
}

function storageSet(items) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.set(items, () => resolve(true));
    } catch {
      resolve(false);
    }
  });
}

async function loadBackendConfig() {
  const saved = await storageGet(STORAGE_KEYS.BACKEND);
  if (saved && typeof saved === "object") {
    state.backendHost = saved.host || DEFAULT_HOST;
    state.backendPort = saved.port || DEFAULT_PORT;
  }
  $("backend-host").value = state.backendHost;
  $("backend-port").value = state.backendPort;
}

async function saveBackendConfig() {
  const host = $("backend-host").value.trim() || DEFAULT_HOST;
  const port = parseInt($("backend-port").value, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    setStatus("backend-status", "端口必须是 1-65535 的整数", "error");
    return;
  }
  state.backendHost = host;
  state.backendPort = port;
  await storageSet({
    [STORAGE_KEYS.BACKEND]: { host, port },
  });
  setStatus("backend-status", `已保存：${getBackendOrigin()}`, "success");
  // 后端地址变更后，缓存的 pluginId 失效
  state.pluginId = null;
}

async function loadApiKey() {
  const key = await storageGet(STORAGE_KEYS.API_KEY);
  state.apiKey = key || null;
  if (key) {
    showApiKeySavedState(maskApiKey(key));
  }
}

async function saveApiKey() {
  const key = $("api-key").value.trim();
  if (!key) {
    setStatus("apikey-status", "请输入 API Key", "error");
    return;
  }
  if (key.length < MIN_API_KEY_LENGTH) {
    setStatus(
      "apikey-status",
      `API Key 长度不足，至少 ${MIN_API_KEY_LENGTH} 字符（当前 ${key.length}）`,
      "error"
    );
    return;
  }

  state.apiKey = key;
  await storageSet({ [STORAGE_KEYS.API_KEY]: key });
  $("api-key").value = "";
  showApiKeySavedState(maskApiKey(key));
  setStatus("apikey-status", "API Key 已保存", "success");
}

async function clearApiKey() {
  state.apiKey = null;
  state.pluginId = null;
  await storageSet({ [STORAGE_KEYS.API_KEY]: null });
  $("api-key").value = "";
  $("btn-clear-apikey").classList.add("hidden");
  $("btn-save-apikey").textContent = "保存 API Key";
  $("api-key").placeholder = "粘贴 OPENAWA_API_KEY（至少 32 字符）";
  setStatus("apikey-status", "API Key 已清除", "info");
  resetCookieState();
}

function showApiKeySavedState(masked) {
  $("btn-clear-apikey").classList.remove("hidden");
  $("btn-save-apikey").textContent = "更新 API Key";
  $("api-key").placeholder = `已保存：${masked}（重新输入可更新）`;
  setStatus("apikey-status", `已保存：${masked}`, "success");
}

// ==================== 后端 API 调用 ====================

/**
 * 获取 openbiliclaw-builtin 插件 ID（带缓存）。
 */
async function getPluginId() {
  if (state.pluginId) return state.pluginId;

  const response = await fetch(`${getBackendApiBase()}/plugins`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(`获取插件列表失败：HTTP ${response.status}`);
  }

  const data = await response.json();
  // 兼容 { items: [...] } 和 [...] 两种返回格式
  const plugins = Array.isArray(data) ? data : (data.items || data.plugins || []);
  const target = plugins.find(
    (p) => p.name === "openbiliclaw-builtin" || p.name === "openbiliclaw_builtin"
  );
  if (!target) {
    throw new Error("后端未找到 openbiliclaw-builtin 插件，请确认插件已注册");
  }

  state.pluginId = target.id;
  return target.id;
}

/**
 * 获取插件当前配置。
 * 后端端点为 GET /config/export（返回 { plugin_id, plugin_name, config }），
 * 注意：不存在 GET /config 端点（会返回 405）。
 */
async function getPluginConfig(pluginId) {
  const response = await fetch(
    `${getBackendApiBase()}/plugins/${pluginId}/config/export`,
    { headers: getAuthHeaders() }
  );
  if (!response.ok) {
    throw new Error(`获取插件配置失败：HTTP ${response.status}`);
  }
  const data = await response.json();
  // 返回结构：{ plugin_id, plugin_name, config: {...} }
  return data.config || data || {};
}

/**
 * 保存插件配置（合并现有配置，避免覆盖其他字段）。
 */
async function savePluginConfig(pluginId, configPatch) {
  // 先获取现有配置，再合并，避免覆盖其他字段
  const currentConfig = await getPluginConfig(pluginId);
  const mergedConfig = { ...currentConfig, ...configPatch };

  const response = await fetch(
    `${getBackendApiBase()}/plugins/${pluginId}/config`,
    {
      method: "PUT",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(mergedConfig),
    }
  );
  if (!response.ok) {
    let errMsg = `HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      errMsg = errJson.detail || errMsg;
    } catch {}
    throw new Error(`保存插件配置失败：${errMsg}`);
  }
  return response.json();
}

// ==================== Cookie 获取 ====================

/**
 * 获取指定平台的所有 Cookie，拼接为 Cookie 字符串。
 * 使用 chrome.cookies.getAll API，按域名后缀匹配。
 */
async function fetchPlatformCookie(platform) {
  const domains = PLATFORM_DOMAINS[platform];
  if (!domains || domains.length === 0) {
    throw new Error(`未知平台：${platform}`);
  }

  const allCookies = [];
  for (const domain of domains) {
    // chrome.cookies.getAll 接受 domain 参数，会匹配该域名及子域名
    const cookies = await new Promise((resolve) => {
      chrome.cookies.getAll({ domain }, (cookies) => resolve(cookies || []));
    });
    allCookies.push(...cookies);
  }

  if (allCookies.length === 0) {
    return null;
  }

  // 去重（不同域名可能有同名 cookie）
  const seen = new Set();
  const uniqueCookies = [];
  for (const cookie of allCookies) {
    const key = `${cookie.domain}:${cookie.name}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueCookies.push(cookie);
    }
  }

  // 拼接为 "name=value; name2=value2" 格式
  const cookieString = uniqueCookies
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  return {
    cookieString,
    length: cookieString.length,
    domain: domains.join(", "),
    count: uniqueCookies.length,
  };
}

// ==================== Cookie 获取与同步流程 ====================

async function handleFetchCookie() {
  const platform = $("platform-select").value;
  state.currentPlatform = platform;
  clearStatus("cookie-status");
  $("btn-fetch-cookie").disabled = true;

  try {
    setStatus("cookie-status", "获取中...", "info");
    const result = await fetchPlatformCookie(platform);
    if (!result) {
      setStatus(
        "cookie-status",
        `未获取到 ${platform} 的 Cookie，请先在浏览器中登录对应平台`,
        "warning"
      );
      $("cookie-preview").classList.add("hidden");
      $("btn-sync-cookie").disabled = true;
      state.currentCookie = null;
      return;
    }

    state.currentCookie = result;
    // 显示掩码预览
    $("cookie-content").textContent = maskCookie(result.cookieString);
    $("cookie-length").textContent = `${result.length} 字符 / ${result.count} 项`;
    $("cookie-preview").classList.remove("hidden");

    setStatus(
      "cookie-status",
      `已获取 ${result.count} 个 Cookie（域名：${result.domain}）`,
      "success"
    );

    // 根据平台是否支持同步，启用/禁用同步按钮
    const syncField = PLATFORM_CONFIG_FIELD[platform];
    if (syncField && state.apiKey) {
      $("btn-sync-cookie").disabled = false;
    } else if (!syncField) {
      $("btn-sync-cookie").disabled = true;
      setStatus(
        "cookie-status",
        `已获取 Cookie，但 ${platform} 暂无对应后端字段，可复制后手动使用`,
        "warning"
      );
    } else {
      $("btn-sync-cookie").disabled = true;
      setStatus(
        "cookie-status",
        "已获取 Cookie，请先保存 API Key 后再同步",
        "warning"
      );
    }
  } catch (err) {
    setStatus("cookie-status", `获取失败：${err.message}`, "error");
    $("cookie-preview").classList.add("hidden");
    state.currentCookie = null;
  } finally {
    $("btn-fetch-cookie").disabled = false;
  }
}

async function handleSyncCookie() {
  if (!state.currentCookie) {
    setStatus("cookie-status", "请先获取 Cookie", "error");
    return;
  }
  if (!state.apiKey) {
    setStatus("cookie-status", "请先保存 API Key", "error");
    return;
  }

  const syncField = PLATFORM_CONFIG_FIELD[state.currentPlatform];
  if (!syncField) {
    setStatus("cookie-status", "该平台暂不支持同步", "error");
    return;
  }

  $("btn-sync-cookie").disabled = true;
  setStatus("cookie-status", "同步中...", "info");

  try {
    const pluginId = await getPluginId();
    const patch = { [syncField]: state.currentCookie.cookieString };
    await savePluginConfig(pluginId, patch);
    setStatus(
      "cookie-status",
      `同步成功：已写入 openbiliclaw-builtin.${syncField}`,
      "success"
    );
    setGlobalStatus("Cookie 同步完成", "success");
  } catch (err) {
    setStatus("cookie-status", `同步失败：${err.message}`, "error");
    // 401/403 时提示 API Key 可能失效
    if (err.message.includes("401") || err.message.includes("403")) {
      setStatus(
        "apikey-status",
        "API Key 可能失效或权限不足，请重新保存",
        "warning"
      );
    }
  } finally {
    $("btn-sync-cookie").disabled = false;
  }
}

function resetCookieState() {
  state.currentCookie = null;
  $("cookie-preview").classList.add("hidden");
  $("btn-sync-cookie").disabled = true;
  clearStatus("cookie-status");
}

// ==================== 平台切换与 UI 事件 ====================

function handlePlatformChange() {
  resetCookieState();
}

function handleShowApiKeyToggle() {
  const input = $("api-key");
  const checkbox = $("show-api-key");
  input.type = checkbox.checked ? "text" : "password";
}

// ==================== 初始化 ====================

async function init() {
  // 绑定事件
  $("btn-save-backend").addEventListener("click", saveBackendConfig);
  $("btn-save-apikey").addEventListener("click", saveApiKey);
  $("btn-clear-apikey").addEventListener("click", clearApiKey);
  $("btn-fetch-cookie").addEventListener("click", handleFetchCookie);
  $("btn-sync-cookie").addEventListener("click", handleSyncCookie);
  $("platform-select").addEventListener("change", handlePlatformChange);
  $("show-api-key").addEventListener("change", handleShowApiKeyToggle);

  // 加载已保存的配置
  await loadBackendConfig();
  await loadApiKey();

  setGlobalStatus("就绪", "info");
}

document.addEventListener("DOMContentLoaded", init);
