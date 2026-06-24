/**
 * 开机自启 IPC 处理器
 */
import { ipcMain, app } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getAutostart, setAutostart } from '../../shared/config-store'

/** 获取开机自启状态 */
export function handleGetAutostart(): boolean {
  return getAutostart()
}

/** 设置开机自启 */
export function handleSetAutostart(_event: unknown, enabled: boolean): boolean {
  try {
    app.setLoginItemSettings({ openAtLogin: enabled })
    setAutostart(enabled)
    return true
  } catch {
    return false
  }
}

/** 注册开机自启 IPC 处理器 */
export function registerAutostartIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.AUTOSTART_GET, handleGetAutostart)
  ipcMain.handle(IPC_CHANNELS.AUTOSTART_SET, handleSetAutostart)
}
