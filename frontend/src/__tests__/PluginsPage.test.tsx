import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import PluginsPage from '@/features/plugins/PluginsPage'
import { pluginsAPI } from '@/shared/api/api'

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: {
    getAll: vi.fn(),
    toggle: vi.fn(),
    uninstall: vi.fn(),
    getPermissions: vi.fn(),
    authorizePermissions: vi.fn(),
    revokePermissions: vi.fn(),
  },
}))

describe('PluginsPage permissions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(pluginsAPI.getAll as any).mockResolvedValue({
      data: [
        {
          id: 'plugin-1',
          name: 'permission-plugin',
          version: '1.0.0',
          enabled: true,
        },
      ],
    })
    ;(pluginsAPI.getPermissions as any).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
      },
    })
    ;(pluginsAPI.authorizePermissions as any).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: ['network:http'],
        missing_permissions: [],
        message: '权限授权成功',
      },
    })
    ;(pluginsAPI.revokePermissions as any).mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
        message: '权限撤销成功',
      },
    })
  })

  afterEach(() => {
    cleanup()
  })

  it('应显示权限弹窗并可授权缺失权限', async () => {
    render(<PluginsPage />)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('权限'))

    await waitFor(() => {
      expect(pluginsAPI.getPermissions).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByText('插件权限')).toBeInTheDocument()
      expect(screen.getByText('network:http')).toBeInTheDocument()
      expect(screen.getByText('待授权')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('授权缺失权限'))

    await waitFor(() => {
      expect(pluginsAPI.authorizePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
      expect(screen.getByText('权限授权成功')).toBeInTheDocument()
    })
  })

  it('应支持撤销已授权权限', async () => {
    ;(pluginsAPI.getPermissions as any)
      .mockResolvedValueOnce({
        data: {
          plugin_id: 'plugin-1',
          plugin_name: 'permission-plugin',
          requested_permissions: ['network:http'],
          granted_permissions: ['network:http'],
          missing_permissions: [],
        },
      })
      .mockResolvedValueOnce({
        data: {
          plugin_id: 'plugin-1',
          plugin_name: 'permission-plugin',
          requested_permissions: ['network:http'],
          granted_permissions: [],
          missing_permissions: ['network:http'],
        },
      })

    render(<PluginsPage />)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByText('权限'))

    await waitFor(() => {
      expect(screen.getByText('撤销')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('撤销'))

    await waitFor(() => {
      expect(pluginsAPI.revokePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
      expect(screen.getByText('已撤销权限: network:http')).toBeInTheDocument()
    })
  })
})
