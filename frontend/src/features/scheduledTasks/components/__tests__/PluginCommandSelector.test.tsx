import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PluginCommandSelector from '../PluginCommandSelector'
import { scheduledTasksAPI } from '@/shared/api/api'
import type { PluginCommandInfo } from '@/shared/api/api'

vi.mock('@/shared/api/api', () => ({
  scheduledTasksAPI: {
    getPluginCommands: vi.fn(),
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    error: vi.fn(),
  },
}))

const command: PluginCommandInfo = {
  plugin_name: 'demo-plugin',
  plugin_version: '1.0.0',
  plugin_description: '测试插件',
  command_name: 'run',
  command_description: '运行命令',
  command_method: 'run',
  parameters: {},
}

describe('PluginCommandSelector 外部选择同步', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(scheduledTasksAPI.getPluginCommands).mockResolvedValue({ data: [command] })
  })

  it('父组件更换回调后向最新回调同步当前选中命令', async () => {
    const firstOnSelect = vi.fn()
    const secondOnSelect = vi.fn()
    const { rerender } = render(
      <PluginCommandSelector
        onSelect={firstOnSelect}
        selectedPluginName="demo-plugin"
        selectedCommandName="run"
      />
    )

    await waitFor(() => {
      expect(firstOnSelect).toHaveBeenCalledWith(command)
    })

    rerender(
      <PluginCommandSelector
        onSelect={secondOnSelect}
        selectedPluginName="demo-plugin"
        selectedCommandName="run"
      />
    )

    expect(secondOnSelect).toHaveBeenCalledWith(command)
  })
})
