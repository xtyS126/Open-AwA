import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import PluginDebugPanel from '../components/PluginDebugPanel'
import { pluginsAPI } from '../services/api'

vi.mock('../services/api', () => ({
  pluginsAPI: {
    getLogs: vi.fn(),
    setLogLevel: vi.fn(),
  },
}))

const PLUGIN_ID = 'test-plugin-id'
const PLUGIN_NAME = 'TestPlugin'

const mockLogsEmpty = {
  data: {
    plugin_id: PLUGIN_ID,
    plugin_name: PLUGIN_NAME,
    level_filter: null,
    total: 0,
    entries: [],
  },
}

const mockLogsWithEntries = {
  data: {
    plugin_id: PLUGIN_ID,
    plugin_name: PLUGIN_NAME,
    level_filter: null,
    total: 2,
    entries: [
      {
        timestamp: '2024-01-01T10:00:00.000Z',
        level: 'INFO',
        message: '插件已初始化',
        plugin_id: PLUGIN_ID,
        extra: {},
      },
      {
        timestamp: '2024-01-01T10:00:01.000Z',
        level: 'ERROR',
        message: '执行失败',
        plugin_id: PLUGIN_ID,
        extra: { code: 500 },
      },
    ],
  },
}

describe('PluginDebugPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(pluginsAPI.getLogs as any).mockResolvedValue(mockLogsEmpty)
    ;(pluginsAPI.setLogLevel as any).mockResolvedValue({
      data: { plugin_id: PLUGIN_ID, plugin_name: PLUGIN_NAME, level: 'INFO' },
    })
  })

  afterEach(() => {
    cleanup()
  })

  it('应显示调试面板标题', async () => {
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => {
      expect(screen.getByText(`${PLUGIN_NAME} 调试面板`)).toBeInTheDocument()
    })
  })

  it('无日志时显示暂无日志提示', async () => {
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => {
      expect(screen.getByText('暂无日志条目')).toBeInTheDocument()
    })
  })

  it('有日志时应显示日志条目', async () => {
    ;(pluginsAPI.getLogs as any).mockResolvedValue(mockLogsWithEntries)
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => {
      expect(screen.getByText('插件已初始化')).toBeInTheDocument()
      expect(screen.getByText('执行失败')).toBeInTheDocument()
    })
  })

  it('应显示日志级别标签', async () => {
    ;(pluginsAPI.getLogs as any).mockResolvedValue(mockLogsWithEntries)
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => {
      const infoEls = screen.getAllByText('INFO')
      const errorEls = screen.getAllByText('ERROR')
      expect(infoEls.length).toBeGreaterThan(0)
      expect(errorEls.length).toBeGreaterThan(0)
    })
  })

  it('点击刷新按钮应重新获取日志', async () => {
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => expect(pluginsAPI.getLogs).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByText('刷新'))
    await waitFor(() => expect(pluginsAPI.getLogs).toHaveBeenCalledTimes(2))
  })

  it('点击日志级别按钮应调用 setLogLevel', async () => {
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => expect(pluginsAPI.getLogs).toHaveBeenCalled())
    const infoButtons = screen.getAllByText('INFO')
    const levelBtn = infoButtons.find(el => el.tagName === 'BUTTON')
    if (levelBtn) {
      fireEvent.click(levelBtn)
      await waitFor(() => {
        expect(pluginsAPI.setLogLevel).toHaveBeenCalledWith(PLUGIN_ID, 'INFO')
      })
    }
  })

  it('切换实时轮询按钮文字应变化', async () => {
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => expect(screen.getByText('实时轮询')).toBeInTheDocument())
    fireEvent.click(screen.getByText('实时轮询'))
    expect(screen.getByText('停止轮询')).toBeInTheDocument()
    fireEvent.click(screen.getByText('停止轮询'))
    expect(screen.getByText('实时轮询')).toBeInTheDocument()
  })

  it('extra 字段有内容时应显示 JSON', async () => {
    ;(pluginsAPI.getLogs as any).mockResolvedValue(mockLogsWithEntries)
    render(<PluginDebugPanel pluginId={PLUGIN_ID} pluginName={PLUGIN_NAME} />)
    await waitFor(() => {
      expect(screen.getByText('{"code":500}')).toBeInTheDocument()
    })
  })
})
