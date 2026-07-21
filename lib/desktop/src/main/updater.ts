/**
 * 自动更新初始化
 */
import { autoUpdater } from 'electron-updater'
import { BrowserWindow } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getUpdateConfig } from '../shared/config-store'
import type { UpdateStatusPayload } from '../shared/types'

/** 向所有窗口发送更新状态 */
function sendUpdateStatus(payload: UpdateStatusPayload): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(IPC_CHANNELS.UPDATE_STATUS_CHANGED, payload)
    }
  }
}

/** 提取错误消息：autoUpdater error 事件参数类型为 Error | string | null */
function toErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  return String(err ?? '未知错误')
}

/** 自动检查的定时器引用（用于退出时清理） */
let autoCheckTimer: NodeJS.Timeout | null = null

/** 是否已初始化（幂等保护，避免重复注册 autoUpdater 监听器） */
let initialized = false

/** 初始化自动更新 */
export function initAutoUpdater(): void {
  // 幂等保护：activate 等场景可能重复调用，避免监听器累积
  if (initialized) {
    return
  }
  initialized = true

  const config = getUpdateConfig()

  // 配置更新源（若指定）
  if (config.source) {
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: config.source,
    })
  }

  // 自动下载：独立于 autoCheck，默认 false（由用户在 UI 触发下载）
  // 修复原 bug：原代码 autoDownload = config.autoCheck 导致开启自动检查即静默下载
  autoUpdater.autoDownload = false
  // 安装时不退出应用（由用户触发 install-and-restart）
  autoUpdater.autoInstallOnAppQuit = false

  // 监听更新事件
  autoUpdater.on('checking-for-update', () => {
    sendUpdateStatus({ status: 'checking' })
  })

  autoUpdater.on('update-available', (info) => {
    sendUpdateStatus({ status: 'available', version: info.version })
  })

  autoUpdater.on('update-not-available', () => {
    sendUpdateStatus({ status: 'not-available' })
  })

  autoUpdater.on('download-progress', (progress) => {
    sendUpdateStatus({ status: 'downloading', progress: progress.percent })
  })

  autoUpdater.on('update-downloaded', (info) => {
    sendUpdateStatus({ status: 'downloaded', version: info.version })
  })

  autoUpdater.on('error', (err) => {
    // 类型守卫：err 可能为 string 或 null
    sendUpdateStatus({ status: 'error', error: toErrorMessage(err) })
  })

  // 启动后延迟 30 秒自动检查更新
  if (config.autoCheck) {
    autoCheckTimer = setTimeout(() => {
      autoUpdater.checkForUpdates().catch((err: unknown) => {
        // 记录日志而非静默吞异常
        log.warn('自动检查更新失败:', toErrorMessage(err))
      })
    }, 30000)
  }
}

/** 清理自动更新资源（在 will-quit 中调用） */
export function disposeAutoUpdater(): void {
  if (autoCheckTimer) {
    clearTimeout(autoCheckTimer)
    autoCheckTimer = null
  }
  initialized = false
}

/** 手动检查更新 */
export async function checkForUpdates(): Promise<void> {
  await autoUpdater.checkForUpdates()
}

/** 下载更新 */
export async function downloadUpdate(): Promise<void> {
  await autoUpdater.downloadUpdate()
}

/** 安装并重启 */
export function installAndRestart(): void {
  autoUpdater.quitAndInstall()
}
