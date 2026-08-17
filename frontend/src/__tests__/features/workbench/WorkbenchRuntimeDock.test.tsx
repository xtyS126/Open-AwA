import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkbenchRuntimeDock from '@/features/workbench/WorkbenchRuntimeDock'
import WorkbenchShell from '@/features/workbench/WorkbenchShell'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

const PROJECT_A = asWorkbenchProjectId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
const PROJECT_B = asWorkbenchProjectId('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')

const mocks = vi.hoisted(() => ({
  createPreview: vi.fn(),
  renewPreview: vi.fn(),
  revokePreview: vi.fn(),
  terminalMounts: 0,
}))

vi.mock('@/features/workbench/WorkbenchContextProvider', () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/features/workbench/WorkbenchProjectBar', () => ({
  default: () => <div>项目栏</div>,
}))

vi.mock('@/features/workbench/WorkbenchProjectSwitchDialog', () => ({
  default: () => null,
}))

vi.mock('@/shared/routing', () => ({
  Outlet: () => <main data-testid="workbench-outlet">子页面</main>,
}))

vi.mock('@/features/vibe-coding/components/TerminalPane', async () => {
  const React = await import('react')
  function MockTerminalPane({
    projectId,
    generation,
    onBindingChange,
  }: {
    projectId: string
    generation: number
    onBindingChange: (sessionId: string | null) => void
  }) {
    React.useEffect(() => {
      mocks.terminalMounts += 1
      onBindingChange(`terminal-${projectId}-${generation}`)
      return () => onBindingChange(null)
    }, [generation, onBindingChange, projectId])
    return <div data-testid="terminal-pane">终端 {projectId}</div>
  }
  return {
    default: MockTerminalPane,
  }
})

vi.mock('@/features/vibe-coding/components/FilePreviewPane', () => ({
  default: ({ projectId, intent }: { projectId: string; intent: { kind: string; previewId?: string } }) => (
    <div data-testid="file-preview-pane">
      {projectId}:{intent.kind}:{intent.previewId ?? ''}
    </div>
  ),
}))

vi.mock('@/features/workbench/workbenchPreviewApi', () => ({
  workbenchPreviewApi: {
    create: mocks.createPreview,
    renew: mocks.renewPreview,
    revoke: mocks.revokePreview,
  },
}))

const projectA = {
  id: PROJECT_A,
  displayName: '项目 A',
  isEnabled: true,
  createdAt: '2026-08-15T00:00:00Z',
  updatedAt: '2026-08-15T00:00:00Z',
  lastOpenedAt: null,
}
const projectB = { ...projectA, id: PROJECT_B, displayName: '项目 B' }

function setReadyProject(projectId = PROJECT_A, generation = 1): void {
  useWorkbenchProjectStore.setState({
    projects: [projectA, projectB],
    currentProjectId: projectId,
    phase: 'ready',
    switchGeneration: generation,
  })
  useWorkbenchRuntimeStore.getState().activateProject(projectId, generation)
  useWorkbenchRuntimeStore.getState().setDockState(projectId, generation, { open: true })
}

describe('WorkbenchRuntimeDock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.terminalMounts = 0
    useWorkbenchRuntimeStore.getState().resetAll()
    useWorkbenchProjectStore.getState().resetForServerChange()
    mocks.createPreview.mockResolvedValue({
      previewId: 'preview-a',
      projectId: PROJECT_A,
      sessionKind: 'terminal',
      sessionId: `terminal-${PROJECT_A}-1`,
      expiresAt: '2026-08-15T12:15:00Z',
    })
    mocks.renewPreview.mockResolvedValue(undefined)
    mocks.revokePreview.mockResolvedValue(undefined)
  })

  it('Shell 在 Outlet 后保持唯一 Dock owner', async () => {
    setReadyProject()
    render(<WorkbenchShell />)

    const shell = screen.getByTestId('workbench-shell')
    expect(shell.lastElementChild).toBe(screen.getByTestId('workbench-runtime-dock'))
    expect(await screen.findAllByTestId('terminal-pane')).toHaveLength(1)
    expect(mocks.terminalMounts).toBe(1)
  })

  it('没有 ready 项目时不启动终端或预览资源', () => {
    useWorkbenchProjectStore.setState({
      currentProjectId: null,
      phase: 'no-selection',
      switchGeneration: 0,
    })

    render(<WorkbenchRuntimeDock />)

    expect(screen.getByText('选择可用项目后可启动终端和 HTTP 预览')).toBeInTheDocument()
    expect(screen.queryByTestId('terminal-pane')).not.toBeInTheDocument()
    expect(mocks.createPreview).not.toHaveBeenCalled()
  })

  it('端口仅用于签发租约，成功后 runtime 只保存 previewId', async () => {
    setReadyProject()
    render(<WorkbenchRuntimeDock />)

    fireEvent.click(screen.getByRole('tab', { name: '预览' }))
    fireEvent.change(screen.getByLabelText('HTTP 预览端口'), {
      target: { value: '5173' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建 HTTP 预览' }))

    await waitFor(() => {
      expect(mocks.createPreview).toHaveBeenCalledWith(PROJECT_A, {
        sessionKind: 'terminal',
        sessionId: `terminal-${PROJECT_A}-1`,
        port: 5173,
      })
    })
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A].previewIntent).toEqual({
      kind: 'web',
      previewId: 'preview-a',
    })
    expect(JSON.stringify(useWorkbenchRuntimeStore.getState().projects[PROJECT_A])).not.toContain('5173')
  })

  it('迟到的旧 generation 租约立即撤销且不回写新桶', async () => {
    let resolveCreate: ((value: {
      previewId: string
      projectId: string
      sessionKind: 'terminal'
      sessionId: string
      expiresAt: string
    }) => void) | undefined
    mocks.createPreview.mockReturnValue(new Promise((resolve) => {
      resolveCreate = resolve
    }))
    setReadyProject(PROJECT_A, 1)
    render(<WorkbenchRuntimeDock />)
    fireEvent.click(screen.getByRole('tab', { name: '预览' }))
    fireEvent.change(screen.getByLabelText('HTTP 预览端口'), {
      target: { value: '5173' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建 HTTP 预览' }))

    await act(async () => {
      setReadyProject(PROJECT_B, 2)
    })
    resolveCreate?.({
      previewId: 'preview-a-stale',
      projectId: PROJECT_A,
      sessionKind: 'terminal',
      sessionId: `terminal-${PROJECT_A}-1`,
      expiresAt: '2026-08-15T12:15:00Z',
    })

    await waitFor(() => {
      expect(mocks.revokePreview).toHaveBeenCalledWith(PROJECT_A, 'preview-a-stale')
    })
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_B].previewIntent).toEqual({ kind: 'none' })
    expect(screen.getByTestId('file-preview-pane')).toHaveTextContent(`${PROJECT_B}:none:`)
  })

  it('关闭 Dock 时撤销当前预览租约', async () => {
    setReadyProject()
    useWorkbenchRuntimeStore.getState().activateProject(PROJECT_A, 1)
    useWorkbenchRuntimeStore.getState().setDockState(PROJECT_A, 1, {
      open: true,
      panel: 'preview',
    })
    useWorkbenchRuntimeStore.getState().setPreviewIntent(PROJECT_A, 1, {
      kind: 'web',
      previewId: 'preview-open',
    })
    render(<WorkbenchRuntimeDock />)

    fireEvent.click(screen.getByRole('button', { name: '关闭运行时面板' }))

    await waitFor(() => {
      expect(mocks.revokePreview).toHaveBeenCalledWith(PROJECT_A, 'preview-open')
    })
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A].previewIntent).toEqual({ kind: 'none' })
  })

  it('替换预览时撤销旧租约但保留新 previewId', async () => {
    setReadyProject()
    useWorkbenchRuntimeStore.getState().setDockState(PROJECT_A, 1, { panel: 'preview' })
    useWorkbenchRuntimeStore.getState().setTerminalBinding(PROJECT_A, 1, {
      kind: 'attached',
      sessionId: `terminal-${PROJECT_A}-1`,
    })
    useWorkbenchRuntimeStore.getState().setPreviewIntent(PROJECT_A, 1, {
      kind: 'web',
      previewId: 'preview-old',
    })
    mocks.createPreview.mockResolvedValue({
      previewId: 'preview-new',
      projectId: PROJECT_A,
      sessionKind: 'terminal',
      sessionId: `terminal-${PROJECT_A}-1`,
      expiresAt: '2026-08-15T12:15:00Z',
    })
    render(<WorkbenchRuntimeDock />)

    fireEvent.click(screen.getByRole('button', { name: '创建 HTTP 预览' }))

    await waitFor(() => {
      expect(mocks.revokePreview).toHaveBeenCalledWith(PROJECT_A, 'preview-old')
    })
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A].previewIntent).toEqual({
      kind: 'web',
      previewId: 'preview-new',
    })
  })
})
