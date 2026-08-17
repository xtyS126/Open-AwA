/**
 * 偏好同步工具。
 * 桥接服务端 profile_data["preferences"] 和浏览器 localStorage。
 * localStorage 是快速本地缓存（防止主题闪现和离线回退），服务端是跨浏览器同步的真实来源。
 */
import { userAPI } from '@/shared/api/authApi'
import { safeSetItem } from '@/shared/utils/safeStorage'
import { asRecord } from '@/shared/types/api'

const PREFERENCE_WRITERS: Record<string, (value: unknown) => void> = {
  theme: (value) => {
    safeSetItem('theme', String(value))
    updateAppSettingsField('theme', value)
  },
  language: (value) => updateAppSettingsField('language', value),
  apiProvider: (value) => updateAppSettingsField('apiProvider', value),
  requireConfirm: (value) => updateAppSettingsField('requireConfirm', value),
  enableAudit: (value) => updateAppSettingsField('enableAudit', value),
  maxToolCallRounds: (value) => updateAppSettingsField('maxToolCallRounds', value),
  selectedModel: (value) => safeSetItem('chat_selected_model', String(value)),
  thinkingEnabled: (value) => safeSetItem('chat_thinking_enabled', value ? 'true' : 'false'),
  thinkingDepth: (value) => safeSetItem('chat_thinking_depth', String(value)),
  outputMode: (value) => safeSetItem('chat_output_mode', String(value)),
}

function updateAppSettingsField(field: string, value: unknown): void {
  try {
    const raw = localStorage.getItem('app_settings')
    if (raw) {
      const settings = asRecord(JSON.parse(raw))
      settings[field] = value
      localStorage.setItem('app_settings', JSON.stringify(settings))
    }
  } catch {
    // localStorage 不可用或数据损坏时静默忽略
  }
}

// 模块级节流状态：5 秒内复用上次成功结果，避免 App 启动期 + 设置页挂载期重复调用
let lastLoadPromise: Promise<Record<string, unknown> | null> | null = null
let lastLoadTimestamp = 0
const PREFERENCE_LOAD_THROTTLE_MS = 5000

/**
 * 从服务端加载偏好并写入 localStorage。
 * 在 App.tsx 中认证成功后调用。
 *
 * 5 秒节流：成功后在 5 秒窗口内的重复调用复用同一 Promise，避免多组件挂载重复拉取。
 * 失败不缓存：返回 null（服务端不可用）时不更新 timestamp，下次调用立即重试。
 *
 * @returns 偏好对象；服务端不可用时返回 null
 */
export async function loadServerPreferences(): Promise<Record<string, unknown> | null> {
  const now = Date.now()
  if (lastLoadPromise && now - lastLoadTimestamp < PREFERENCE_LOAD_THROTTLE_MS) {
    return lastLoadPromise
  }
  // 同步占位 timestamp，避免并发调用在 Promise 完成前绕过节流
  lastLoadTimestamp = now
  lastLoadPromise = doLoadServerPreferences().then((prefs) => {
    if (prefs === null) {
      // 失败重置节流，允许立即重试
      lastLoadTimestamp = 0
      lastLoadPromise = null
    } else {
      // 成功则更新 timestamp 为完成时刻，让 5 秒窗口从完成时起算
      lastLoadTimestamp = Date.now()
    }
    return prefs
  })
  return lastLoadPromise
}

/**
 * 实际执行拉取与写入的内部函数。
 * 服务端不可用时返回 null（不抛错），由调用方决定降级策略。
 */
async function doLoadServerPreferences(): Promise<Record<string, unknown> | null> {
  try {
    const response = await userAPI.getPreferences()
    const prefs: Record<string, unknown> = response.data?.preferences || {}
    for (const [key, value] of Object.entries(prefs)) {
      const writer = PREFERENCE_WRITERS[key]
      if (writer && value !== null && value !== undefined) {
        writer(value)
      }
    }
    return prefs
  } catch {
    // 服务端不可用时保留本地值
    return null
  }
}

/**
 * 测试辅助：重置节流状态。仅供单元测试在 beforeEach 调用。
 */
export function __resetPreferenceThrottle(): void {
  lastLoadPromise = null
  lastLoadTimestamp = 0
}

/**
 * 在本地状态已更新后，将单个偏好变更同步到服务端。
 * 触发即忘，不阻塞 UI；失败时记录显式警告并返回 false（标记"未同步"状态）。
 * @returns 是否同步成功
 */
export function syncPreferenceToServer(key: string, value: unknown): Promise<boolean> {
  return userAPI.updatePreferences({ [key]: value })
    .then(() => true)
    .catch((error: unknown) => {
      // 失败显式警告：跨设备偏好已分叉（本地已更新、服务端未同步）
      console.warn(`[preferenceSync] 偏好 "${key}" 同步到服务端失败，跨设备偏好将不一致:`,
        error instanceof Error ? error.message : String(error))
      return false
    })
}
