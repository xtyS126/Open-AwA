/**
 * Shell 相关 IPC 处理器
 * 处理外部链接打开和文件资源管理器定位
 */
import { ipcMain, shell, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/** 允许的外部链接协议白名单 */
const ALLOWED_PROTOCOLS = ['http:', 'https:']

/**
 * 在默认浏览器中打开外部链接
 * 仅允许 http/https 协议，防止协议注入
 */
async function handleOpenExternal(
  _event: IpcMainInvokeEvent,
  { url }: { url: string }
): Promise<{ success: boolean; error?: string }> {
  try {
    const parsed = new URL(url)
    if (!ALLOWED_PROTOCOLS.includes(parsed.protocol)) {
      return { success: false, error: `不允许的协议: ${parsed.protocol}` }
    }
    await shell.openExternal(url)
    return { success: true }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    log.error('打开外部链接失败:', err)
    return { success: false, error: message }
  }
}

/**
 * 在文件资源管理器中定位并选中指定文件
 */
async function handleShowItem(
  _event: IpcMainInvokeEvent,
  { filePath }: { filePath: string }
): Promise<{ success: boolean; error?: string }> {
  try {
    shell.showItemInFolder(filePath)
    return { success: true }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    log.error('在资源管理器中显示文件失败:', err)
    return { success: false, error: message }
  }
}

/** 注册 Shell 相关 IPC 处理器 */
export function registerShellIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.SHELL_OPEN_EXTERNAL, handleOpenExternal)
  ipcMain.handle(IPC_CHANNELS.SHELL_SHOW_ITEM, handleShowItem)
}