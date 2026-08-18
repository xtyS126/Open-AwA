/**
 * 主进程与渲染进程共享的类型定义
 */

/** 后端地址配置 */
export interface BackendConfig {
  url: string
}

/** 窗口边界配置 */
export interface WindowBounds {
  x: number | null
  y: number | null
  width: number
  height: number
}

/** 窗口配置 */
export interface WindowConfig {
  bounds: WindowBounds
  isMaximized: boolean
}

/** 托盘配置 */
export interface TrayConfig {
  minimizeToTray: boolean
}

/** 自动更新配置 */
export interface UpdateConfig {
  autoCheck: boolean
  source: string
}

/** 应用完整配置（electron-store 存储结构） */
export interface AppConfig {
  backend: BackendConfig
  window: WindowConfig
  tray: TrayConfig
  autostart: boolean
  update: UpdateConfig
  companion: CompanionConfig
  pet: PetConfig
}

/** 默认配置 */
export const DEFAULT_CONFIG: AppConfig = {
  backend: {
    url: '',
  },
  window: {
    bounds: { x: null, y: null, width: 1440, height: 900 },
    isMaximized: false,
  },
  tray: {
    minimizeToTray: true,
  },
  autostart: false,
  update: {
    autoCheck: true,
    source: '',
  },
  companion: {
    notificationsEnabled: true,
    bondNotifications: true,
    diaryNotifications: true,
    inactivityReminder: true,
  },
  pet: {
    enabled: false,
    petId: '',
    position: { x: -1, y: -1 },
    size: 250,
    alwaysOnTop: true,
  },
}

/** 后端连接测试结果 */
export interface ConnectionTestResult {
  ok: boolean
  latency?: number
  error?: string
}

/** 系统通知请求参数 */
export interface NotificationRequest {
  title: string
  body: string
  url?: string
}

/** 通知点击事件参数 */
export interface NotificationClickedPayload {
  url?: string
}

/** 自动更新状态 */
export type UpdateStatus = 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'

/** 自动更新状态变更事件 */
export interface UpdateStatusPayload {
  status: UpdateStatus
  progress?: number
  error?: string
  version?: string
}

/** preload 注入的后端信息 */
export interface BackendInfo {
  url: string
  version: string
}

/** 陪伴事件类型 */
export type CompanionEventType = 'bond_upgrade' | 'milestone' | 'diary_ready' | 'inactivity_reminder'

/** 陪伴通知请求参数 */
export interface CompanionNotifyRequest {
  type: CompanionEventType
  title: string
  body: string
  navigateTo?: string
}

/** 陪伴通知点击事件参数 */
export interface CompanionNotifyClickedPayload {
  type: CompanionEventType
  navigateTo?: string
}

/** 陪伴通知配置 */
export interface CompanionConfig {
  notificationsEnabled: boolean
  bondNotifications: boolean
  diaryNotifications: boolean
  inactivityReminder: boolean
}

/** 宠物悬浮窗配置 */
export interface PetConfig {
  enabled: boolean
  petId: string
  position: { x: number; y: number }
  size: number
  alwaysOnTop: boolean
}

/** preload 注入的桌面端 API */
export interface DesktopApi {
  platform: string
  isPackaged: boolean
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
    on: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}
