import '@testing-library/jest-dom/vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  usePluginConfig,
  usePluginConfigActions,
  usePluginConfigSchema,
  usePluginDelete,
  usePluginDetail,
  usePluginImport,
  usePluginList,
  usePluginPermissions,
  usePluginToggle,
} from '@/features/plugins/hooks'
import type { Plugin } from '@/features/dashboard/dashboard'
import { pluginsAPI } from '@/shared/api/api'

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: {
    getAll: vi.fn(),
    upload: vi.fn(),
    importFromUrl: vi.fn(),
    uninstall: vi.fn(),
    getOne: vi.fn(),
    saveConfig: vi.fn(),
    getConfigSchema: vi.fn(),
    resetConfig: vi.fn(),
    exportConfig: vi.fn(),
    toggle: vi.fn(),
    getPermissions: vi.fn(),
    authorizePermissions: vi.fn(),
    revokePermissions: vi.fn(),
  },
}))

describe('features/plugins/hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('usePluginList 应支持失败后 retry 重新加载', async () => {
    ;(pluginsAPI.getAll as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('list failed'))
      .mockResolvedValueOnce({ data: [{ id: 'plugin-1', name: 'demo', version: '1.0.0', enabled: true }] })

    const { result } = renderHook(() => usePluginList())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
      expect(result.current.error).toBe('list failed')
    })

    await act(async () => {
      await result.current.retry()
    })

    expect(result.current.error).toBeNull()
    expect(result.current.plugins).toHaveLength(1)
    expect(pluginsAPI.getAll).toHaveBeenCalledTimes(2)
  })

  it('usePluginImport 应支持导入失败后 retry', async () => {
    ;(pluginsAPI.importFromUrl as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('import failed'))
      .mockResolvedValueOnce({ data: { ok: true } })

    const { result } = renderHook(() => usePluginImport())

    await act(async () => {
      await expect(result.current.importFromUrl('https://example.com/demo.zip')).rejects.toThrow('import failed')
    })
    expect(result.current.error).toBe('import failed')

    await act(async () => {
      await result.current.retry()
    })
    expect(result.current.error).toBeNull()
    expect(pluginsAPI.importFromUrl).toHaveBeenCalledTimes(2)
  })

  it('usePluginDelete 应返回批量删除成功与失败列表', async () => {
    ;(pluginsAPI.uninstall as ReturnType<typeof vi.fn>).mockImplementation(async (pluginId: string) => {
      if (pluginId === 'plugin-2') {
        throw new Error('cannot delete')
      }
      return { data: { ok: true } }
    })

    const { result } = renderHook(() => usePluginDelete())
    let batchResult: Awaited<ReturnType<typeof result.current.deleteBatch>> | null = null

    await act(async () => {
      batchResult = await result.current.deleteBatch(['plugin-1', 'plugin-2'])
    })

    expect(batchResult?.successIds).toEqual(['plugin-1'])
    expect(batchResult?.failed).toHaveLength(1)
    expect(batchResult?.failed[0].pluginId).toBe('plugin-2')
  })

  it('usePluginDetail 应按 pluginId 拉取详情', async () => {
    ;(pluginsAPI.getOne as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'plugin-1', name: 'demo', version: '1.0.0', enabled: true },
    })

    const { result } = renderHook(() => usePluginDetail('plugin-1'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
      expect(result.current.detail?.id).toBe('plugin-1')
    })
  })

  it('usePluginConfig 应支持保存失败后 retrySave', async () => {
    ;(pluginsAPI.getOne as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'plugin-1', name: 'demo', version: '1.0.0', enabled: true, config: { api_key: 'old' } },
    })
    ;(pluginsAPI.saveConfig as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('save failed'))
      .mockResolvedValueOnce({ data: { plugin_id: 'plugin-1', plugin_name: 'demo', config: { api_key: 'new' } } })

    const { result } = renderHook(() => usePluginConfig('plugin-1'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
      expect(result.current.config).toEqual({ api_key: 'old' })
    })

    await act(async () => {
      await expect(result.current.saveConfig({ api_key: 'new' })).rejects.toThrow('save failed')
    })
    expect(result.current.saveError).toBe('save failed')

    await act(async () => {
      await result.current.retrySave()
    })
    expect(result.current.saveError).toBeNull()
    expect(pluginsAPI.saveConfig).toHaveBeenCalledTimes(2)
  })

  it('usePluginConfigSchema 应支持失败重试', async () => {
    ;(pluginsAPI.getConfigSchema as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('schema failed'))
      .mockResolvedValueOnce({
        data: {
          plugin_id: 'plugin-1',
          plugin_name: 'demo',
          schema: { type: 'object', properties: {} },
          default_config: {},
          current_config: {},
          config_file_exists: true,
        },
      })

    const { result } = renderHook(() => usePluginConfigSchema('plugin-1'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
      expect(result.current.error).toBe('schema failed')
    })

    await act(async () => {
      await result.current.retry()
    })

    expect(result.current.error).toBeNull()
    expect(result.current.schemaPayload?.plugin_id).toBe('plugin-1')
  })

  it('usePluginConfigActions 应提供保存/重置/导出能力', async () => {
    ;(pluginsAPI.saveConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { plugin_id: 'plugin-1', plugin_name: 'demo', config: { mode: 'safe' } },
    })
    ;(pluginsAPI.resetConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { plugin_id: 'plugin-1', plugin_name: 'demo', config: { mode: 'default' } },
    })
    ;(pluginsAPI.exportConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { plugin_id: 'plugin-1', plugin_name: 'demo', config: { mode: 'safe' } },
    })

    const { result } = renderHook(() => usePluginConfigActions('plugin-1'))

    await act(async () => {
      expect(await result.current.saveConfig({ mode: 'safe' })).toEqual({ mode: 'safe' })
      expect(await result.current.resetConfig()).toEqual({ mode: 'default' })
      expect(await result.current.exportConfig()).toEqual({ mode: 'safe' })
    })
  })

  it('usePluginPermissions 与 usePluginToggle 应处理权限与启停操作', async () => {
    ;(pluginsAPI.getPermissions as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'demo',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
      },
    })
    ;(pluginsAPI.authorizePermissions as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'demo',
        requested_permissions: ['network:http'],
        granted_permissions: ['network:http'],
        missing_permissions: [],
        message: 'ok',
      },
    })
    ;(pluginsAPI.revokePermissions as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'demo',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
        message: 'ok',
      },
    })
    ;(pluginsAPI.toggle as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ok: true } })

    const permissionsHook = renderHook(() => usePluginPermissions())
    const toggleHook = renderHook(() => usePluginToggle())

    await act(async () => {
      await permissionsHook.result.current.refreshPermissions({ id: 'plugin-1', name: 'demo' } as Pick<Plugin, 'id' | 'name'>)
      await permissionsHook.result.current.authorizePermissions('plugin-1', ['network:http'])
      await permissionsHook.result.current.revokePermissions('plugin-1', ['network:http'])
      await toggleHook.result.current.toggle('plugin-1')
    })

    expect(pluginsAPI.getPermissions).toHaveBeenCalledWith('plugin-1')
    expect(pluginsAPI.authorizePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
    expect(pluginsAPI.revokePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
    expect(pluginsAPI.toggle).toHaveBeenCalledWith('plugin-1')
  })
})
