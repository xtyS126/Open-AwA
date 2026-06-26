/**
 * 窗口控制 IPC 处理器
 *
 * 注意：窗口最大化状态变化的事件桥接已移至 window.ts 的 attachWindowEventBridge
 * 统一管理，避免重复监听和时序问题（窗口创建前注册监听器失效）。
 */
import { ipcMain } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getMinimizeToTray } from '../../shared/config-store'
import { getMainWindow } from '../window'

/** 最小化窗口 */
export function handleMinimize(): void {
  const win = getMainWindow()
  win?.minimize()
}

/** 切换最大化 */
export function handleMaximize(): { isMaximized: boolean } {
  const win = getMainWindow()
  if (!win) return { isMaximized: false }
  if (win.isMaximized()) {
    win.unmaximize()
  } else {
    win.maximize()
  }
  return { isMaximized: win.isMaximized() }
}

/** 关闭窗口（按配置最小化到托盘或退出） */
export function handleClose(): void {
  const win = getMainWindow()
  if (!win) return
  if (getMinimizeToTray()) {
    win.hide()
  } else {
    win.close()
  }
}

/** 查询窗口是否最大化 */
export function handleIsMaximized(): boolean {
  const win = getMainWindow()
  return win?.isMaximized() ?? false
}

/** 注册窗口控制 IPC 处理器 */
export function registerWindowIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.WINDOW_MINIMIZE, handleMinimize)
  ipcMain.handle(IPC_CHANNELS.WINDOW_MAXIMIZE, handleMaximize)
  ipcMain.handle(IPC_CHANNELS.WINDOW_CLOSE, handleClose)
  ipcMain.handle(IPC_CHANNELS.WINDOW_IS_MAXIMIZED, handleIsMaximized)
}
