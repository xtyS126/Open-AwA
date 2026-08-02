import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkspacePage from '../WorkspacePage'
import { useWorkspaceStore } from '../store/workspaceStore'

const { listWorkspacesMock } = vi.hoisted(() => ({
  listWorkspacesMock: vi.fn(),
}))

vi.mock('../workspaceApi', () => ({
  workspaceApi: {
    list: listWorkspacesMock,
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('WorkspacePage 工作区加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useWorkspaceStore.setState({ workspaces: [], currentWorkspaceId: 'default' })
    listWorkspacesMock.mockResolvedValue({
      workspaces: [{
        id: 'default',
        name: '默认工作区',
        description: '默认描述',
        agent_type: 'default',
        is_default: true,
        is_enabled: true,
        skills_count: 0,
        channels_count: 0,
        created_at: null,
        updated_at: null,
      }],
    })
  })

  it('普通重新渲染不会重复请求工作区列表', async () => {
    const { rerender } = render(<WorkspacePage />)

    await waitFor(() => {
      expect(screen.getByText('默认工作区')).toBeInTheDocument()
    })
    expect(listWorkspacesMock).toHaveBeenCalledTimes(1)

    rerender(<WorkspacePage />)

    expect(listWorkspacesMock).toHaveBeenCalledTimes(1)
  })
})
