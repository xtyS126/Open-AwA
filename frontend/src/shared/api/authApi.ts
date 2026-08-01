/**
 * 认证与用户 API 模块。封装登录、API Key 管理、用户资料、登录设备、用户偏好、密码修改端点。自 api.ts 拆分而来。
 */
import { api, refreshCsrfToken, persistApiKey as _persistApiKey } from './client'

/**
 * 持久化 API Key 后拉取 CSRF token。
 *
 * 此函数包装了 client.ts 的 persistApiKey：在 API Key 持久化成功后，
 * 等待 per-session CSRF token 初始化，确保认证状态发布后发出的首个状态变更请求
 * 已携带 X-CSRF-Token。
 *
 * 调用时机：登录成功后由 LoginPage 调用。CSRF token 拉取失败不阻塞登录流程，
 * 后续 POST/PUT/PATCH/DELETE 请求会因缺失 CSRF token 被后端拒绝（响应拦截器会自动重试一次）。
 *
 * @param key 已验证通过的 API Key
 */
export async function persistApiKey(key: string): Promise<void> {
  _persistApiKey(key)
  await refreshCsrfToken()
}

export const authAPI = {
  /** 使用用户名密码登录（兼容旧 JWT 路径，前端通常直接使用 API Key） */
  login: (username: string, password: string) => {
    let formData: string | URLSearchParams
    try {
      formData = new URLSearchParams({ username, password })
    } catch {
      formData = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
    }
    return api.post('/auth/login', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })
  },
  /** 获取当前用户信息（API Key 认证） */
  getMe: () => api.get('/auth/me'),
  /** 登出（清除 JWT Cookie，API Key 模式下通常不需要） */
  logout: () => api.post('/auth/logout'),
  /** 轮转 API Key */
  rotateApiKey: (confirm: boolean = true) =>
    api.post('/auth/rotate-api-key', { confirm }),
}

export interface UserProfileAnalysis {
  interests?: string[]
  total_actions?: number
  active_hours?: string[]
  [key: string]: unknown
}

export interface UserProfile {
  user_id: string
  username: string
  nickname?: string | null
  avatar_url?: string | null
  email?: string | null
  phone?: string | null
  profile: UserProfileAnalysis
}

export interface UserProfileUpdatePayload {
  nickname?: string
  email?: string
  phone?: string
}

export interface LoginDeviceItem {
  id: number
  device_type: string
  ip_address?: string | null
  user_agent?: string | null
  logged_in_at: string
  last_active_at: string
  is_online: boolean
  is_current: boolean
}

export interface UserPreferencesResponse {
  preferences: Record<string, unknown>
}

export interface AvatarUploadResponse {
  avatar_url: string
  message: string
}

export const userAPI = {
  getProfile: () => api.get<UserProfile>('/user/profile'),
  updateProfile: (payload: UserProfileUpdatePayload) => api.put<{ message: string }>('/user/profile', payload),
  uploadAvatar: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<AvatarUploadResponse>('/user/avatar', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
  getDevices: () => api.get<LoginDeviceItem[]>('/user/devices'),
  revokeDevice: (deviceId: number) => api.post<{ message: string }>(`/user/devices/${deviceId}/revoke`),
  getPreferences: () => api.get<UserPreferencesResponse>('/user/preferences'),
  updatePreferences: (preferences: Record<string, unknown>) =>
    api.put<UserPreferencesResponse>('/user/preferences', { preferences }),
}

export const passwordAPI = {
  change: (oldPassword: string, newPassword: string, confirmPassword: string) =>
    api.put<{ message: string }>('/auth/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
}
