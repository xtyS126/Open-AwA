/**
 * 自动更新 IPC 处理器
 */
import { ipcMain } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { checkForUpdates, downloadUpdate, installAndRestart } from '../updater'

/** 注册更新 IPC 处理器 */
export function registerUpdateIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.UPDATE_CHECK, async () => {
    try {
      await checkForUpdates()
      return { status: 'checking' }
    } catch (err) {
      return { status: 'error', error: err instanceof Error ? err.message : String(err) }
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_DOWNLOAD, async () => {
    try {
      await downloadUpdate()
    } catch {
      // 静默处理
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_INSTALL_AND_RESTART, () => {
    installAndRestart()
  })
}
