/**
 * 陪伴通知 IPC 处理器
 * 负责接收渲染进程的陪伴通知请求，创建系统原生通知，
 * 并在通知被点击时回传事件到渲染进程。
 */
import { ipcMain, Notification, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import type { CompanionNotifyRequest } from '../../shared/types'
import { getMainWindow } from '../window'

/**
 * 处理陪伴通知请求
 * 创建系统原生通知，并在点击时通知渲染进程导航到对应页面。
 */
export function handleCompanionNotify(
  _event: IpcMainInvokeEvent,
  request: CompanionNotifyRequest
): { success: boolean } {
  // 部分平台 Notification 可能不可用
  if (!Notification.isSupported()) {
    log.warn('[companion] 当前平台不支持系统通知')
    return { success: false }
  }

  const notification = new Notification({
    title: request.title,
    body: request.body,
  })

  // 点击通知：聚焦主窗口并通知渲染进程
  notification.on('click', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
      // 通知渲染进程，携带事件类型和导航路径
      win.webContents.send(IPC_CHANNELS.COMPANION_NOTIFY_CLICKED, {
        type: request.type,
        navigateTo: request.navigateTo,
      })
    }
  })

  notification.show()
  log.info('[companion] 陪伴通知已发送', { type: request.type, title: request.title })
  return { success: true }
}

/** 注册陪伴通知 IPC 处理器 */
export function registerCompanionIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.COMPANION_NOTIFY, handleCompanionNotify)
}