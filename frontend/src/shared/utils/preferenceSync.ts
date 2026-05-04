/**
 * 偏好同步工具。
 * 桥接服务端 profile_data["preferences"] 和浏览器 localStorage。
 * localStorage 是快速本地缓存（防止主题闪现和离线回退），服务端是跨浏览器同步的真实来源。
 */
import { userAPI } from '@/shared/api/api'
import { safeSetItem } from '@/shared/utils/safeStorage'

const PREFERENCE_WRITERS: Record<string, (value: any) => void> = {
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

function updateAppSettingsField(field: string, value: any): void {
  try {
    const raw = localStorage.getItem('app_settings')
    if (raw) {
      const settings = JSON.parse(raw)
      if (typeof settings === 'object' && settings !== null) {
        settings[field] = value
        localStorage.setItem('app_settings', JSON.stringify(settings))
      }
    }
  } catch {
    // localStorage 不可用或数据损坏时静默忽略
  }
}

/**
 * 从服务端加载偏好并写入 localStorage。
 * 在 App.tsx 中认证成功后调用。
 */
export async function loadServerPreferences(): Promise<void> {
  try {
    const response = await userAPI.getPreferences()
    const prefs: Record<string, any> = response.data?.preferences || {}
    for (const [key, value] of Object.entries(prefs)) {
      const writer = PREFERENCE_WRITERS[key]
      if (writer && value !== null && value !== undefined) {
        writer(value)
      }
    }
  } catch {
    // 服务端不可用时保留本地值
  }
}

/**
 * 在本地状态已更新后，将单个偏好变更同步到服务端。
 * 触发即忘，不阻塞 UI。
 */
export function syncPreferenceToServer(key: string, value: any): void {
  userAPI.updatePreferences({ [key]: value }).catch(() => {
    // 静默失败，localStorage 已更新
  })
}
