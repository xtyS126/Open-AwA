import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
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
    upload: vi.fn(),
    importFromUrl: vi.fn(),
  },
}))

describe('PluginsPage permissions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
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
    ;(pluginsAPI.uninstall as any).mockResolvedValue({ data: { message: 'ok' } })
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
    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

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

    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

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

  it('应支持搜索与批量删除并显示 Toast', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    ;(pluginsAPI.getAll as any).mockResolvedValue({
      data: [
        { id: 'plugin-1', name: 'alpha-plugin', version: '1.0.0', enabled: true, description: 'first' },
        { id: 'plugin-2', name: 'beta-plugin', version: '1.0.0', enabled: true, description: 'second' },
      ],
    })

    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
      expect(screen.getByText('alpha-plugin')).toBeInTheDocument()
      expect(screen.getByText('beta-plugin')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('搜索插件名称 / 版本 / 作者 / 简介'), {
      target: { value: 'alpha' },
    })

    expect(screen.getByText('alpha-plugin')).toBeInTheDocument()
    expect(screen.queryByText('beta-plugin')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('全选当前结果'))
    fireEvent.click(screen.getByText('批量删除(1)'))

    await waitFor(() => {
      expect(pluginsAPI.uninstall).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByText('已批量删除 1 个插件')).toBeInTheDocument()
    })
  })

  it('应在本地导入时校验 zip 扩展名与文件大小', async () => {
    const { container } = render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).toBeInTheDocument()

    const invalidExtensionFile = new File(['content'], 'plugin.txt', { type: 'text/plain' })
    fireEvent.change(fileInput, { target: { files: [invalidExtensionFile] } })

    expect(globalThis.alert).toHaveBeenCalledWith('只支持 .zip 格式的插件包')
    expect(pluginsAPI.upload).not.toHaveBeenCalled()

    const oversizedFile = new File(['content'], 'plugin.zip', { type: 'application/zip' })
    Object.defineProperty(oversizedFile, 'size', { value: 51 * 1024 * 1024 })
    fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

    expect(globalThis.alert).toHaveBeenCalledWith('插件包大小无效或已超过 50MB 限制')
    expect(pluginsAPI.upload).not.toHaveBeenCalled()
  })

  it('应在远程导入时去除 URL 首尾空白并成功调用接口', async () => {
    ;(pluginsAPI.importFromUrl as any).mockResolvedValue({ data: { message: 'ok' } })

    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    const urlInput = screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）')
    fireEvent.change(urlInput, { target: { value: '   https://example.com/plugin.zip   ' } })
    fireEvent.click(screen.getByText('URL 导入'))

    await waitFor(() => {
      expect(pluginsAPI.importFromUrl).toHaveBeenCalledWith('https://example.com/plugin.zip', 30)
      expect(screen.getByText('远程 URL 导入成功')).toBeInTheDocument()
    })
  })

  it('应在本地 zip 导入成功后刷新列表并提示成功', async () => {
    ;(pluginsAPI.upload as any).mockResolvedValue({ data: { message: 'ok' } })
    const { container } = render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const zipFile = new File(['content'], 'demo-plugin.zip', { type: 'application/zip' })
    fireEvent.change(fileInput, { target: { files: [zipFile] } })

    await waitFor(() => {
      expect(pluginsAPI.upload).toHaveBeenCalledTimes(1)
      expect(screen.getByText('插件导入成功')).toBeInTheDocument()
    })
  })

  it('应在远程 URL 为空时给出提示且不发起导入请求', async () => {
    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）'), {
      target: { value: '   ' },
    })
    fireEvent.click(screen.getByText('URL 导入'))

    expect(pluginsAPI.importFromUrl).not.toHaveBeenCalled()
    expect(screen.getByText('请输入远程 URL')).toBeInTheDocument()
  })

  it('应支持从 config 回退解析作者与简介', async () => {
    ;(pluginsAPI.getAll as any).mockResolvedValue({
      data: [
        {
          id: 'plugin-3',
          name: 'fallback-plugin',
          version: '2.0.0',
          enabled: true,
          config: {
            author: 'config-author',
            description:
              '这是一个来自配置的超长简介，用于覆盖简介回退逻辑。这段文字会超过八十个字符，以便展示查看简介与收起简介按钮并验证交互。',
          },
        },
      ],
    })

    render(<BrowserRouter><PluginsPage /></BrowserRouter>)

    await waitFor(() => {
      expect(screen.getByText('作者：config-author')).toBeInTheDocument()
      expect(
        screen.getByText(
          '这是一个来自配置的超长简介，用于覆盖简介回退逻辑。这段文字会超过八十个字符，以便展示查看简介与收起简介按钮并验证交互。',
        ),
      ).toBeInTheDocument()
    })
  })
})
