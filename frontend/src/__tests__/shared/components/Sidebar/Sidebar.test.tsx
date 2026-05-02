import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
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
  it('展示导航链接：定时任务、插件等模块入口', () => {
    render(
      <MemoryRouter initialEntries={['/plugins/manage']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/scheduled-tasks')
    expect(screen.getByRole('link', { name: '插件' })).toHaveAttribute('href', '/plugins/manage')
  })

  it('任意插件子路由都应高亮同一个插件入口', () => {
    render(
      <MemoryRouter initialEntries={['/plugins/config/test-plugin']}>
        <Sidebar />
      </MemoryRouter>
    )

    const pluginLink = screen.getByRole('link', { name: '插件' })
    expect(pluginLink.className).toMatch(/active/)
  })
})
