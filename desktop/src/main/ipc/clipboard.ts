/**
 * 剪贴板 IPC 处理器
 * 处理剪贴板读写操作
 */
import { ipcMain, clipboard, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/**
 * 读取剪贴板文本内容
 */
async function handleClipboardRead(): Promise<{ text: string }> {
  try {
    const text = clipboard.readText()
    return { text }
  } catch (err) {
    log.error('读取剪贴板失败:', err)
    return { text: '' }
  }
}

/**
 * 写入文本到剪贴板
 */
async function handleClipboardWrite(
  _event: IpcMainInvokeEvent,
  { text }: { text: string }
): Promise<{ success: boolean }> {
  try {
    clipboard.writeText(text)
    return { success: true }
  } catch (err) {
    log.error('写入剪贴板失败:', err)
    return { success: false }
  }
}

/** 注册剪贴板 IPC 处理器 */
export function registerClipboardIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.CLIPBOARD_READ, handleClipboardRead)
  ipcMain.handle(IPC_CHANNELS.CLIPBOARD_WRITE, handleClipboardWrite)
}