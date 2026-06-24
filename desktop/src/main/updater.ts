/**
 * 自动更新初始化
 */
import { autoUpdater } from 'electron-updater'
import { BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getUpdateConfig } from '../shared/config-store'
import type { UpdateStatusPayload } from '../shared/types'

/** 向所有窗口发送更新状态 */
function sendUpdateStatus(payload: UpdateStatusPayload): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send(IPC_CHANNELS.UPDATE_STATUS_CHANGED, payload)
  }
}

/** 初始化自动更新 */
export function initAutoUpdater(): void {
  const config = getUpdateConfig()

  // 配置更新源（若指定）
  if (config.source) {
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: config.source,
    })
  }

  // 自动下载
  autoUpdater.autoDownload = config.autoCheck
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
    sendUpdateStatus({ status: 'error', error: err.message })
  })

  // 启动后延迟 30 秒自动检查更新
  if (config.autoCheck) {
    setTimeout(() => {
      autoUpdater.checkForUpdates().catch(() => {
        // 静默失败
      })
    }, 30000)
  }
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
