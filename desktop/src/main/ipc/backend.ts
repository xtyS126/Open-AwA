/**
 * 后端地址管理 IPC 处理器
 */
import { ipcMain, BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getBackendUrl, setBackendUrl } from '../../shared/config-store'
import type { ConnectionTestResult } from '../../shared/types'

/** 获取后端 URL */
export async function handleGetUrl(): Promise<string> {
  return getBackendUrl()
}

/** 设置后端 URL */
export async function handleSetUrl(
  _event: unknown,
  { url }: { url: string }
): Promise<{ success: boolean }> {
  try {
    setBackendUrl(url)
    // 通知所有窗口后端 URL 已变更
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC_CHANNELS.BACKEND_URL_CHANGED, { url })
    }
    // 通知主进程引导完成（首次启动场景）
    ipcMain.emit('backend:url-saved')
    return { success: true }
  } catch {
    return { success: false }
  }
}

/** 测试后端连通性 */
export async function handleTestConnection(
  _event: unknown,
  { url }: { url: string }
): Promise<ConnectionTestResult> {
  const start = Date.now()
  try {
    // 构造健康检查 URL
    const healthUrl = url.endsWith('/api') ? `${url}/health` : `${url}/api/health`
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
