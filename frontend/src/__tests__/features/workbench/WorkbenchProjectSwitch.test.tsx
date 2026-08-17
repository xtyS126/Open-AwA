import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkbenchShell from '@/features/workbench/WorkbenchShell'
import { useCodingStore } from '@/features/coding/store/codingStore'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

const mocks = vi.hoisted(() => ({
  patchContext: vi.fn(),
  writeFile: vi.fn(),
}))

vi.mock('@/features/workbench/WorkbenchContextProvider', () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/shared/routing', () => ({
  Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
  Outlet: () => <div>工作台叶子页面</div>,
}))

vi.mock('@/features/workbench/workbenchApi', () => ({
  workbenchApi: {
    patchContext: mocks.patchContext,
  },
  getWorkbenchErrorMessage: (error: unknown) => error instanceof Error ? error.message : '请求失败',
  isWorkbenchContextConflict: () => false,
}))

vi.mock('@/features/coding/codingApi', () => ({
  codingApi: {
    writeFile: mocks.writeFile,
  },
}))

const PROJECT_A = asWorkbenchProjectId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
const PROJECT_B = asWorkbenchProjectId('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
const projectA = {
  id: PROJECT_A,
  displayName: '项目 A',
  isEnabled: true,
  createdAt: '2026-08-12T00:00:00Z',
  updatedAt: '2026-08-12T00:00:00Z',
  lastOpenedAt: null,
}
const projectB = { ...projectA, id: PROJECT_B, displayName: '项目 B' }

describe('Workbench 共享项目切换', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useWorkbenchProjectStore.getState().resetForServerChange()
    useWorkbenchProjectStore.setState({
      projects: [projectA, projectB],
      currentProjectId: PROJECT_A,
      contextEtag: '"v1"',
      phase: 'ready',
      activeScopeKey: 'server-a|user-a',
    })
    useCodingStore.setState({
      projectId: PROJECT_A,
      projectGeneration: 4,
      switchingToProjectId: null,
      projectSnapshots: {},
      openFiles: [{
        path: 'src/app.ts',
        name: 'app.ts',
        content: 'changed',
        isDirty: true,
        language: 'typescript',
      }],
      activeFilePath: 'src/app.ts',
      fileTree: null,
      gitChanges: [],
      gitBranch: '',
      diffMode: false,
    })
    mocks.writeFile.mockResolvedValue({ path: 'src/app.ts', written: true, size: 7 })
    mocks.patchContext.mockResolvedValue({
      project: projectB,
      updatedAt: '2026-08-12T00:00:01Z',
      etag: '"v2"',
    })
  })

  it('顶栏切换遇到 dirty buffer 时先显示统一决策框且取消不 PATCH', async () => {
    render(<WorkbenchShell />)

    fireEvent.change(screen.getByLabelText('切换工作台项目'), {
      target: { value: PROJECT_B },
    })

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('src/app.ts')
    expect(mocks.patchContext).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '取消' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(mocks.patchContext).not.toHaveBeenCalled()
    expect(useWorkbenchProjectStore.getState().currentProjectId).toBe(PROJECT_A)
  })

  it('统一决策框保存后再提交服务端 context 并关闭', async () => {
    render(<WorkbenchShell />)
    fireEvent.change(screen.getByLabelText('切换工作台项目'), {
      target: { value: PROJECT_B },
    })
    await screen.findByRole('alertdialog')

    fireEvent.click(screen.getByRole('button', { name: '保存并切换' }))

    await waitFor(() => expect(mocks.patchContext).toHaveBeenCalledWith(PROJECT_B, '"v1"'))
    expect(mocks.writeFile).toHaveBeenCalledWith(PROJECT_A, 'src/app.ts', 'changed')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(useWorkbenchProjectStore.getState().currentProjectId).toBe(PROJECT_B)
  })
})
