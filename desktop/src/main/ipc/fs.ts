/**
 * 文件系统 IPC 处理器
 * 处理文件打开、保存、读写操作，含路径越权校验
 */
import { ipcMain, dialog, type IpcMainInvokeEvent } from 'electron'
import fs from 'fs'
import path from 'path'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/** 允许文件读写的安全根目录列表 */
const ALLOWED_ROOTS = [
  require('os').homedir(),
  require('electron').app.getPath('userData'),
  require('electron').app.getPath('documents'),
  require('electron').app.getPath('downloads'),
  require('electron').app.getPath('desktop'),
]

/**
 * 校验文件路径是否在允许的目录内，防止路径穿越
 * @param filePath - 待校验的文件路径
 * @returns 解析后的绝对路径；若越权则返回 null
 */
function resolveSafePath(filePath: string): string | null {
  const resolved = path.resolve(filePath)
  for (const root of ALLOWED_ROOTS) {
    if (resolved.startsWith(root + path.sep) || resolved === root) {
      return resolved
    }
  }
  return null
}

/**
 * 打开文件选择对话框，读取选中文件内容
 */
async function handleOpenFile(): Promise<{ filePath: string | null; content: string | null; canceled: boolean }> {
  try {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
    })
    if (result.canceled || result.filePaths.length === 0) {
      return { filePath: null, content: null, canceled: true }
    }
    const filePath = result.filePaths[0]
    const content = fs.readFileSync(filePath, 'utf-8')
    return { filePath, content, canceled: false }
  } catch (err) {
    log.error('打开文件失败:', err)
    return { filePath: null, content: null, canceled: true }
  }
}

/**
 * 保存文件对话框，将内容写入选中路径
 */
async function handleSaveFile(
  _event: IpcMainInvokeEvent,
  { content, defaultPath }: { content: string; defaultPath?: string }
): Promise<{ filePath: string | null; success: boolean }> {
  try {
    const result = await dialog.showSaveDialog({
      defaultPath,
    })
    if (result.canceled || !result.filePath) {
      return { filePath: null, success: false }
    }
    fs.writeFileSync(result.filePath, content, 'utf-8')
    return { filePath: result.filePath, success: true }
  } catch (err) {
    log.error('保存文件失败:', err)
    return { filePath: null, success: false }
  }
}

/**
 * 读取指定路径的文件内容（含路径越权校验）
 */
async function handleReadFile(
  _event: IpcMainInvokeEvent,
  { filePath }: { filePath: string }
): Promise<{ content: string | null; success: boolean; error?: string }> {
  try {
    const safePath = resolveSafePath(filePath)
    if (!safePath) {
      return { content: null, success: false, error: '路径越权：不允许访问该目录' }
    }
    if (!fs.existsSync(safePath)) {
      return { content: null, success: false, error: '文件不存在' }
    }
    const content = fs.readFileSync(safePath, 'utf-8')
    return { content, success: true }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    log.error('读取文件失败:', err)
    return { content: null, success: false, error: message }
  }
}

/**
 * 将内容写入指定路径的文件（含路径越权校验）
 */
async function handleWriteFile(
  _event: IpcMainInvokeEvent,
  { filePath, content }: { filePath: string; content: string }
): Promise<{ success: boolean; error?: string }> {
  try {
    const safePath = resolveSafePath(filePath)
    if (!safePath) {
      return { success: false, error: '路径越权：不允许访问该目录' }
    }
    // 确保父目录存在
    const dir = path.dirname(safePath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }
    fs.writeFileSync(safePath, content, 'utf-8')
    return { success: true }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    log.error('写入文件失败:', err)
    return { success: false, error: message }
  }
}

/** 注册文件系统 IPC 处理器 */
export function registerFsIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.FS_OPEN_FILE, handleOpenFile)
  ipcMain.handle(IPC_CHANNELS.FS_SAVE_FILE, handleSaveFile)
  ipcMain.handle(IPC_CHANNELS.FS_READ_FILE, handleReadFile)
  ipcMain.handle(IPC_CHANNELS.FS_WRITE_FILE, handleWriteFile)
}