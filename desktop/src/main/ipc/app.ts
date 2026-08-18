/**
 * 应用信息 IPC 处理器
 */
import { ipcMain, app } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/** 获取应用版本 */
export function handleGetVersion(): string {
  return app.getVersion()
}

/** 获取操作系统平台 */
export function handleGetPlatform(): string {
  return process.platform
}

/** 确认当前运行在桌面端（Electron） */
export function handleIsDesktop(): boolean {
  return true
}

/** 注册应用信息 IPC 处理器 */
export function registerAppIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.APP_GET_VERSION, handleGetVersion)
  ipcMain.handle(IPC_CHANNELS.APP_GET_PLATFORM, handleGetPlatform)
  ipcMain.handle(IPC_CHANNELS.APP_IS_DESKTOP, handleIsDesktop)
}
