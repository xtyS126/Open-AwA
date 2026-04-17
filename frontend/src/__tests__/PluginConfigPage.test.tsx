import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PluginConfigPage from '@/features/plugins/PluginConfigPage'

const mockUsePluginList = vi.fn()
const mockUsePluginConfigSchema = vi.fn()
const mockUsePluginConfigActions = vi.fn()

const mockSaveConfig = vi.fn()
const mockResetConfig = vi.fn()
const mockExportConfig = vi.fn()
const mockRetrySchema = vi.fn()
const mockRetryAction = vi.fn()

vi.mock('@/features/plugins/hooks', () => ({
  usePluginList: () => mockUsePluginList(),
  usePluginConfigSchema: () => mockUsePluginConfigSchema(),
  usePluginConfigActions: () => mockUsePluginConfigActions(),
}))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/plugins/config/plugin-1']}>
      <Routes>
        <Route path="/plugins/config/:pluginId" element={<PluginConfigPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PluginConfigPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(URL, 'createObjectURL', {
      writable: true,
      value: vi.fn(() => 'blob:test-url'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      writable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    mockSaveConfig.mockResolvedValue({})
    mockResetConfig.mockResolvedValue({ mode: 'safe', enabled: true, api_key: '' })
    mockExportConfig.mockResolvedValue({ api_key: 'abcd' })

    mockUsePluginList.mockReturnValue({
      plugins: [{ id: 'plugin-1', name: 'demo-plugin' }],
      loading: false,
      error: null,
      retry: vi.fn(),
      refresh: vi.fn(),
      setPlugins: vi.fn(),
    })
    mockUsePluginConfigSchema.mockReturnValue({
      schemaPayload: {
        plugin_id: 'plugin-1',
        plugin_name: 'demo-plugin',
        schema: {
          type: 'object',
          properties: {
            api_key: {
              type: 'string',
              title: 'API Key',
              minLength: 4,
            },
            mode: {
              type: 'string',
              title: '模式',
              enum: ['safe', 'fast'],
            },
            enabled: {
              type: 'boolean',
              title: '启用',
            },
            script: {
              type: 'string',
              title: '脚本',
              'x-component': 'code-editor',
            },
            file_path: {
              type: 'string',
              title: '文件路径',
              'x-component': 'file-picker',
            },
          },
          required: ['api_key'],
        },
        default_config: { mode: 'safe', enabled: true },
        current_config: { api_key: 'abcd', script: 'print(1)', file_path: '' },
        config_file_exists: true,
      },
      loading: false,
      error: null,
      retry: mockRetrySchema,
      refresh: mockRetrySchema,
    })
    mockUsePluginConfigActions.mockReturnValue({
      loading: false,
      error: null,
      retry: mockRetryAction,
      saveConfig: mockSaveConfig,
      resetConfig: mockResetConfig,
      exportConfig: mockExportConfig,
    })
  })

  it('应根据 schema 渲染五类控件', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('API Key')).toBeInTheDocument()
    })

    expect(screen.getByDisplayValue('abcd')).toBeInTheDocument()
    expect(screen.getByDisplayValue('safe')).toBeInTheDocument()
    expect(screen.getByDisplayValue('print(1)')).toBeInTheDocument()
    expect(screen.getByLabelText('file_path-file-picker')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('应实时校验并阻止非法保存', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('API Key')).toBeInTheDocument()
    })

    const apiKeyInput = screen.getByDisplayValue('abcd')
    fireEvent.change(apiKeyInput, { target: { value: '' } })

    await waitFor(() => {
      expect(screen.getByText('API Key为必填项')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('保存配置'))
    await waitFor(() => {
      expect(mockSaveConfig).not.toHaveBeenCalled()
    })
  })

  it('应通过确认弹窗执行重置默认', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('重置默认')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('重置默认'))
    fireEvent.click(screen.getByText('确认'))

    await waitFor(() => {
      expect(mockResetConfig).toHaveBeenCalled()
    })
  })

  it('应通过确认弹窗执行导出配置', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('导出配置')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('导出配置'))
    fireEvent.click(screen.getByText('确认'))

    await waitFor(() => {
      expect(mockExportConfig).toHaveBeenCalled()
      expect((URL.createObjectURL as unknown as ReturnType<typeof vi.fn>)).toHaveBeenCalled()
    })
  })

  it('应在导入配置后可回滚到导入前快照', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('导入配置')).toBeInTheDocument()
    })

    const importInput = document.querySelector('input[type="file"][accept="application/json,.json"]') as HTMLInputElement
    const importFile = new File([JSON.stringify({ api_key: 'imported-key' })], 'config.json', { type: 'application/json' })
    Object.defineProperty(importFile, 'text', {
      value: vi.fn(async () => JSON.stringify({ api_key: 'imported-key' })),
    })
    fireEvent.change(importInput, { target: { files: [importFile] } })
    await waitFor(() => {
      expect(screen.getByText('确认')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('确认'))

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'imported-key' }))
      expect(screen.getByDisplayValue('imported-key')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('回滚到导入前'))

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'abcd' }))
      expect(screen.getByText('已回滚到导入前配置')).toBeInTheDocument()
    })
  })
})
