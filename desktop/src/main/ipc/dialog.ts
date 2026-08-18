/**
 * 对话框 IPC 处理器
 * 处理消息提示和确认对话框
 */
import { ipcMain, dialog, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/**
 * 显示消息对话框
 * 支持 info / warning / error 三种类型
 */
async function handleDialogMessage(
  _event: IpcMainInvokeEvent,
  { type, title, message }: { type: 'info' | 'warning' | 'error'; title: string; message: string }
): Promise<{ success: boolean }> {
  try {
    // 将 type 映射为 dialog 的 type 和图标
    const typeMap: Record<string, 'info' | 'warning' | 'error'> = {
      info: 'info',
      warning: 'warning',
      error: 'error',
    }
    await dialog.showMessageBox({
      type: typeMap[type] || 'info',
      title,
      message,
    })
    return { success: true }
  } catch (err) {
    log.error('显示消息对话框失败:', err)
    return { success: false }
  }
}

/**
 * 显示确认对话框
 * 返回用户是否点击了确认
 */
async function handleDialogConfirm(
  _event: IpcMainInvokeEvent,
  { title, message }: { title: string; message: string }
): Promise<{ confirmed: boolean }> {
  try {
    const result = await dialog.showMessageBox({
      type: 'question',
      title,
      message,
      buttons: ['取消', '确认'],
      defaultId: 1,
      cancelId: 0,
    })
    return { confirmed: result.response === 1 }
  } catch (err) {
    log.error('显示确认对话框失败:', err)
    return { confirmed: false }
  }
}

/**
 * 显示错误对话框（便捷方法，等价于 type: 'error' 的消息对话框）
 */
async function handleDialogError(
  _event: IpcMainInvokeEvent,
  { title, message }: { title: string; message: string }
): Promise<{ success: boolean }> {
  return handleDialogMessage(_event, { type: 'error', title, message })
}

/** 注册对话框 IPC 处理器 */
export function registerDialogIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.DIALOG_MESSAGE, handleDialogMessage)
  ipcMain.handle(IPC_CHANNELS.DIALOG_CONFIRM, handleDialogConfirm)
  ipcMain.handle(IPC_CHANNELS.DIALOG_ERROR, handleDialogError)
}