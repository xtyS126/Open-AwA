import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: vi.fn().mockResolvedValue({ data: [] }), getLongTerm: vi.fn().mockResolvedValue({ data: [] }) },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }) }
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

describe('Sidebar', () => {
  it('展示插件分支并提供插件管理/插件配置子入口', () => {
    render(
      <MemoryRouter initialEntries={['/plugins/manage']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/scheduled-tasks')
    expect(screen.getByRole('link', { name: '插件管理' })).toHaveAttribute('href', '/plugins/manage')
    expect(screen.getByRole('link', { name: '插件配置' })).toHaveAttribute('href', '/plugins/config/default')
  })

  it('点击插件分支可折叠和展开子入口', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    )

    const pluginBranchButton = screen.getByRole('button', { name: '插件' })
    expect(screen.queryByRole('link', { name: '插件管理' })).not.toBeInTheDocument()

    fireEvent.click(pluginBranchButton)
    expect(screen.getByRole('link', { name: '插件管理' })).toBeInTheDocument()

    fireEvent.click(pluginBranchButton)
    expect(screen.queryByRole('link', { name: '插件管理' })).not.toBeInTheDocument()
  })
})
