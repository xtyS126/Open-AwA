import { StrictMode } from 'react'
import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkbenchContextProvider from '@/features/workbench/WorkbenchContextProvider'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'
import { useAuthStore } from '@/shared/store/authStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

const apiMocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  getContext: vi.fn(),
  patchContext: vi.fn(),
}))

vi.mock('@/features/workbench/workbenchApi', () => ({
  workbenchApi: apiMocks,
  getWorkbenchErrorMessage: () => '请求失败',
  isWorkbenchContextConflict: () => false,
}))

class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = []
  onmessage: ((event: MessageEvent) => void) | null = null

  constructor(readonly name: string) {
    FakeBroadcastChannel.instances.push(this)
  }

  postMessage(): void {}
  close(): void {}
}

describe('WorkbenchContextProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeBroadcastChannel.instances = []
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    useWorkbenchProjectStore.getState().resetForServerChange()
    useWorkbenchRuntimeStore.getState().resetAll()
    useAuthStore.setState({
      user: { id: 'user-a', username: 'user-a' },
      isAuthenticated: true,
    })
    apiMocks.listProjects.mockResolvedValue({ items: [] })
    apiMocks.getContext.mockResolvedValue({ project: null, updatedAt: null, etag: '"v1"' })
  })

  it('StrictMode 重放复用 hydration，并在 focus 与跨标签消息时刷新', async () => {
    render(
      <StrictMode>
        <WorkbenchContextProvider><div>子页面</div></WorkbenchContextProvider>
      </StrictMode>,
    )

    await waitFor(() => expect(apiMocks.getContext).toHaveBeenCalledTimes(1))

    act(() => window.dispatchEvent(new Event('focus')))
    await waitFor(() => expect(apiMocks.getContext).toHaveBeenCalledTimes(2))

    const channel = FakeBroadcastChannel.instances.at(-1)
    act(() => channel?.onmessage?.(new MessageEvent('message', {
      data: { type: 'context-changed', scopeKey: useWorkbenchProjectStore.getState().activeScopeKey },
    })))
    await waitFor(() => expect(apiMocks.getContext).toHaveBeenCalledTimes(3))
  })

  it('登出时清空项目上下文且不再请求', async () => {
    const projectId = asWorkbenchProjectId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    useWorkbenchRuntimeStore.getState().activateProject(projectId, 1)
    const view = render(
      <WorkbenchContextProvider><div>子页面</div></WorkbenchContextProvider>,
    )
    await waitFor(() => expect(apiMocks.getContext).toHaveBeenCalledTimes(1))

    act(() => useAuthStore.setState({ user: null, isAuthenticated: false }))
    view.rerender(<WorkbenchContextProvider><div>子页面</div></WorkbenchContextProvider>)

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      projects: [],
      currentProjectId: null,
      phase: 'idle',
    })
    expect(useWorkbenchRuntimeStore.getState().projects).toEqual({})
    expect(apiMocks.getContext).toHaveBeenCalledTimes(1)
  })

  it('hydration 失败写入错误状态且不留下未处理拒绝', async () => {
    apiMocks.listProjects.mockRejectedValue(new Error('服务不可用'))

    render(<WorkbenchContextProvider><div>子页面</div></WorkbenchContextProvider>)

    await waitFor(() => {
      expect(useWorkbenchProjectStore.getState()).toMatchObject({
        phase: 'error',
        error: '请求失败',
      })
    })
  })
})
