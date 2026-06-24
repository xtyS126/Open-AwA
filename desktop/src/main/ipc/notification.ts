/**
 * 系统通知 IPC 处理器
 */
import { ipcMain, Notification } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import type { NotificationRequest } from '../../shared/types'
import { getMainWindow } from '../window'

/** 显示系统通知 */
export function handleShowNotification(
  _event: unknown,
  request: NotificationRequest
): void {
  const notification = new Notification({
    title: request.title,
    body: request.body,
  })

  // 点击通知：聚焦主窗口并通知渲染进程跳转
  notification.on('click', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
      // 通知渲染进程（携带 url 用于页面跳转）
      win.webContents.send(IPC_CHANNELS.NOTIFICATION_CLICKED, { url: request.url })
    }
  })

  notification.show()
}

/** 注册通知 IPC 处理器 */
export function registerNotificationIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.NOTIFICATION_SHOW, handleShowNotification)
}
