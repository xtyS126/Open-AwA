import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkbenchProjectsPage from '@/features/workbench/WorkbenchProjectsPage'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  listProjects: vi.fn(),
  getContext: vi.fn(),
  patchContext: vi.fn(),
}))

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useNavigate: () => mocks.navigate,
}))

vi.mock('@/features/workbench/workbenchApi', () => ({
  workbenchApi: mocks,
  getWorkbenchErrorMessage: (error: unknown) => error instanceof Error ? error.message : '请求失败',
  isWorkbenchContextConflict: () => false,
}))

const PROJECT_ID = asWorkbenchProjectId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
const project = {
  id: PROJECT_ID,
  displayName: 'Open-AwA',
  isEnabled: true,
  createdAt: '2026-08-12T00:00:00Z',
  updatedAt: '2026-08-12T00:00:00Z',
  lastOpenedAt: null,
}

describe('WorkbenchProjectsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useWorkbenchProjectStore.getState().resetForServerChange()
    useWorkbenchProjectStore.setState({
      projects: [project],
      currentProjectId: null,
      phase: 'no-selection',
      activeScopeKey: 'server-a|user-a',
      contextEtag: '"v1"',
    })
    mocks.createProject.mockResolvedValue(project)
    mocks.updateProject.mockResolvedValue(project)
    mocks.deleteProject.mockResolvedValue(undefined)
    mocks.listProjects.mockResolvedValue({ items: [project] })
    mocks.getContext.mockResolvedValue({ project: null, updatedAt: null, etag: '"v1"' })
    mocks.patchContext.mockResolvedValue({ project, updatedAt: 'now', etag: '"v2"' })
  })

  it('展示项目列表并可登记项目', async () => {
    render(<WorkbenchProjectsPage />)
    expect(screen.getByRole('heading', { name: '工作台项目' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Open-AwA' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '登记项目' }))
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByLabelText('服务器绝对路径'), { target: { value: 'D:\\work\\new' } })
    fireEvent.click(screen.getByRole('button', { name: '确认登记' }))

    await waitFor(() => expect(mocks.createProject).toHaveBeenCalledWith({
      displayName: '新项目',
      root: 'D:\\work\\new',
    }))
  })

  it('支持选择后进入 Editor 或 Agents', async () => {
    render(<WorkbenchProjectsPage />)

    fireEvent.click(screen.getByRole('button', { name: '在编辑器中打开 Open-AwA' }))
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith({ to: '/workbench/editor' }))

    fireEvent.click(screen.getByRole('button', { name: '在 Agents 中打开 Open-AwA' }))
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith({ to: '/workbench/agents' }))
    expect(mocks.patchContext).toHaveBeenCalledWith(PROJECT_ID, expect.anything())
  })

  it('支持重命名、禁用与删除登记且删除确认不暗示删除磁盘', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('主仓库')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<WorkbenchProjectsPage />)

    fireEvent.click(screen.getByRole('button', { name: '重命名 Open-AwA' }))
    await waitFor(() => expect(mocks.updateProject).toHaveBeenCalledWith(PROJECT_ID, {
      displayName: '主仓库',
    }))

    fireEvent.click(screen.getByRole('button', { name: '禁用 Open-AwA' }))
    await waitFor(() => expect(mocks.updateProject).toHaveBeenCalledWith(PROJECT_ID, {
      isEnabled: false,
    }))

    fireEvent.click(screen.getByRole('button', { name: '删除 Open-AwA' }))
    expect(confirmSpy).toHaveBeenCalledWith(
      '只移除 Open-AwA 登记，不删除磁盘目录。确认删除“Open-AwA”的登记吗？',
    )
    await waitFor(() => expect(mocks.deleteProject).toHaveBeenCalledWith(PROJECT_ID))
  })

  it('呈现可操作错误并保留当前选择', async () => {
    useWorkbenchProjectStore.setState({ currentProjectId: PROJECT_ID, phase: 'ready' })
    mocks.updateProject.mockRejectedValue(new Error('项目仍有运行中资源，请先关闭终端或 Agent 会话'))
    render(<WorkbenchProjectsPage />)

    fireEvent.click(screen.getByRole('button', { name: '禁用 Open-AwA' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('项目仍有运行中资源')
    expect(useWorkbenchProjectStore.getState().currentProjectId).toBe(PROJECT_ID)
  })
})
