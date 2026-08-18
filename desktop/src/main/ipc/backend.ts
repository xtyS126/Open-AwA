/**
 * 后端地址管理 IPC 处理器
 */
import { ipcMain, BrowserWindow, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getBackendUrl, setBackendUrl } from '../../shared/config-store'
import type { ConnectionTestResult } from '../../shared/types'

/** 校验后端 URL 协议白名单（仅允许 http/https），防止 file://、javascript:// 等滥用 */
function validateBackendUrl(url: string): { valid: boolean; error?: string } {
  if (!url || typeof url !== 'string') {
    return { valid: false, error: 'URL 不能为空' }
  }
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return { valid: false, error: `不支持的协议: ${parsed.protocol}，仅允许 http/https` }
    }
    return { valid: true }
  } catch {
    return { valid: false, error: 'URL 格式无效' }
  }
}

/** 获取后端 URL */
export async function handleGetUrl(): Promise<string> {
  return getBackendUrl()
}

/** 设置后端 URL */
export async function handleSetUrl(
  _event: IpcMainInvokeEvent,
  { url }: { url: string }
): Promise<{ success: boolean; error?: string }> {
  const validation = validateBackendUrl(url)
  if (!validation.valid) {
    return { success: false, error: validation.error }
  }
  try {
    setBackendUrl(url)
    // 通知所有窗口后端 URL 已变更
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) {
        win.webContents.send(IPC_CHANNELS.BACKEND_URL_CHANGED, { url })
      }
    }
    // 通知主进程引导完成（首次启动场景）
    ipcMain.emit('backend:url-saved')
    return { success: true }
  } catch (err) {
    // 记录日志而非静默吞异常
    log.error('设置后端 URL 失败:', err)
    return { success: false, error: err instanceof Error ? err.message : String(err) }
  }
}

/** 测试后端连通性 */
export async function handleTestConnection(
  _event: IpcMainInvokeEvent,
  { url }: { url: string }
): Promise<ConnectionTestResult> {
  const validation = validateBackendUrl(url)
  if (!validation.valid) {
    return { ok: false, error: validation.error }
  }
  const start = Date.now()
  try {
    // 构造健康检查 URL
    const healthUrl = url.replace(/\/+$/, '') + '/health'
    const response = await fetch(healthUrl, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    })
    const latency = Date.now() - start
    if (response.ok) {
      return { ok: true, latency }
    }
    return { ok: false, latency, error: `HTTP ${response.status}` }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err)
    return { ok: false, error: errorMsg }
  }
}

/** 注册后端地址相关 IPC 处理器 */
export function registerBackendIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.BACKEND_GET_URL, handleGetUrl)
  ipcMain.handle(IPC_CHANNELS.BACKEND_SET_URL, handleSetUrl)
  ipcMain.handle(IPC_CHANNELS.BACKEND_TEST_CONNECTION, handleTestConnection)
}
