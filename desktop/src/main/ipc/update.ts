/**
 * 自动更新 IPC 处理器
 */
import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { checkForUpdates, downloadUpdate, installAndRestart } from '../updater'

/** 注册更新 IPC 处理器 */
export function registerUpdateIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.UPDATE_CHECK, async () => {
    try {
      await checkForUpdates()
      return { status: 'checking' }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      log.warn('检查更新失败:', errorMsg)
      return { status: 'error', error: errorMsg }
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_DOWNLOAD, async () => {
    try {
      await downloadUpdate()
      return { success: true }
    } catch (err) {
      // 记录日志而非静默吞异常
      const errorMsg = err instanceof Error ? err.message : String(err)
      log.error('下载更新失败:', errorMsg)
      return { success: false, error: errorMsg }
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_INSTALL_AND_RESTART, (_event: IpcMainInvokeEvent) => {
    installAndRestart()
    return { success: true }
  })
}
