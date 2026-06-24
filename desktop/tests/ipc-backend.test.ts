import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'
import { getConfigStore, getBackendUrl, setBackendUrl } from '../src/shared/config-store'

describe('后端地址 IPC', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 清空 config store
    getConfigStore().clear()
  })

  it('registerBackendIpcHandlers 注册所有后端相关 IPC 通道', async () => {
    const { registerBackendIpcHandlers } = await import('../src/main/ipc/backend')
    registerBackendIpcHandlers()
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:get-url', expect.any(Function))
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:set-url', expect.any(Function))
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:test-connection', expect.any(Function))
  })

  it('handleGetUrl 返回当前后端 URL', async () => {
    setBackendUrl('http://test:8000/api')
    const { handleGetUrl } = await import('../src/main/ipc/backend')
    const result = await handleGetUrl()
    expect(result).toBe('http://test:8000/api')
  })

  it('handleSetUrl 保存后端 URL 并返回 success', async () => {
    const { handleSetUrl } = await import('../src/main/ipc/backend')
    const result = await handleSetUrl(null, { url: 'http://new:9000/api' })
    expect(result).toEqual({ success: true })
    expect(getBackendUrl()).toBe('http://new:9000/api')
  })

  it('handleTestConnection 测试可达的后端返回 ok', async () => {
    // mock fetch
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 }) as unknown as typeof fetch
    const { handleTestConnection } = await import('../src/main/ipc/backend')
    const result = await handleTestConnection(null, { url: 'http://test:8000/api' })
    expect(result.ok).toBe(true)
    expect(result.latency).toBeGreaterThanOrEqual(0)
  })

  it('handleTestConnection 测试不可达的后端返回 error', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('ECONNREFUSED')) as unknown as typeof fetch
    const { handleTestConnection } = await import('../src/main/ipc/backend')
    const result = await handleTestConnection(null, { url: 'http://unreachable:9999/api' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('ECONNREFUSED')
  })
})
