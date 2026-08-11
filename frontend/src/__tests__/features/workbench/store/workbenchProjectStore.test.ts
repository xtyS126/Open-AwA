import { beforeEach, describe, expect, it, vi } from 'vitest'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'

const apiMocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  getContext: vi.fn(),
  patchContext: vi.fn(),
}))

vi.mock('@/features/workbench/workbenchApi', () => ({
  workbenchApi: {
    listProjects: apiMocks.listProjects,
    getContext: apiMocks.getContext,
    patchContext: apiMocks.patchContext,
  },
  getWorkbenchErrorMessage: () => '请求失败',
  isWorkbenchContextConflict: () => false,
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

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('workbenchProjectStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useWorkbenchProjectStore.getState().resetForServerChange()
  })

  it('并行加载 projects 与 context 且 StrictMode 重放复用同一在途请求', async () => {
    const listRequest = deferred<{ items: typeof projectA[] }>()
    const contextRequest = deferred<{
      project: typeof projectA
      updatedAt: string
      etag: string
    }>()
    apiMocks.listProjects.mockReturnValue(listRequest.promise)
    apiMocks.getContext.mockReturnValue(contextRequest.promise)

    const first = useWorkbenchProjectStore.getState().hydrate('server-a|user-a')
    const second = useWorkbenchProjectStore.getState().hydrate('server-a|user-a')

    expect(apiMocks.listProjects).toHaveBeenCalledTimes(1)
    expect(apiMocks.getContext).toHaveBeenCalledTimes(1)
    listRequest.resolve({ items: [projectA, projectB] })
    contextRequest.resolve({
      project: projectA,
      updatedAt: '2026-08-12T00:00:00Z',
      etag: '"v1"',
    })
    await Promise.all([first, second])

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      projects: [projectA, projectB],
      currentProjectId: PROJECT_A,
      contextEtag: '"v1"',
      phase: 'ready',
    })
  })

  it('选择请求完成前不乐观切换，失败后保留旧项目', async () => {
    const switchRequest = deferred<never>()
    useWorkbenchProjectStore.setState({
      projects: [projectA, projectB],
      currentProjectId: PROJECT_A,
      contextEtag: '"v1"',
      phase: 'ready',
      activeScopeKey: 'server-a|user-a',
    })
    apiMocks.patchContext.mockReturnValue(switchRequest.promise)

    const pending = useWorkbenchProjectStore.getState().selectProject(PROJECT_B)
    expect(useWorkbenchProjectStore.getState().currentProjectId).toBe(PROJECT_A)

    switchRequest.reject(new Error('切换失败'))
    await expect(pending).rejects.toThrow('切换失败')
    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      currentProjectId: PROJECT_A,
      phase: 'ready',
      error: '请求失败',
    })
  })

  it('选择成功使用 ETag 并递增 generation', async () => {
    useWorkbenchProjectStore.setState({
      projects: [projectA, projectB],
      currentProjectId: PROJECT_A,
      contextEtag: '"v1"',
      phase: 'ready',
      switchGeneration: 3,
      activeScopeKey: 'server-a|user-a',
    })
    apiMocks.patchContext.mockResolvedValue({
      project: projectB,
      updatedAt: '2026-08-12T00:00:01Z',
      etag: '"v2"',
    })

    await useWorkbenchProjectStore.getState().selectProject(PROJECT_B)

    expect(apiMocks.patchContext).toHaveBeenCalledWith(PROJECT_B, '"v1"')
    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      currentProjectId: PROJECT_B,
      contextEtag: '"v2"',
      switchGeneration: 4,
      phase: 'ready',
    })
  })

  it('服务器切换后旧请求完成不会污染新 scope', async () => {
    const oldList = deferred<{ items: typeof projectA[] }>()
    const oldContext = deferred<{ project: typeof projectA; updatedAt: string; etag: string }>()
    apiMocks.listProjects
      .mockReturnValueOnce(oldList.promise)
      .mockResolvedValueOnce({ items: [projectB] })
    apiMocks.getContext
      .mockReturnValueOnce(oldContext.promise)
      .mockResolvedValueOnce({ project: projectB, updatedAt: 'new', etag: '"new"' })

    const stale = useWorkbenchProjectStore.getState().hydrate('server-a|user-a')
    useWorkbenchProjectStore.getState().resetForServerChange()
    await useWorkbenchProjectStore.getState().hydrate('server-b|user-a')
    oldList.resolve({ items: [projectA] })
    oldContext.resolve({ project: projectA, updatedAt: 'old', etag: '"old"' })
    await stale

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      activeScopeKey: 'server-b|user-a',
      projects: [projectB],
      currentProjectId: PROJECT_B,
      contextEtag: '"new"',
    })
  })

  it('切换 scope 后立即清空旧用户项目再等待新响应', async () => {
    const nextList = deferred<{ items: typeof projectB[] }>()
    const nextContext = deferred<{ project: typeof projectB; updatedAt: string; etag: string }>()
    useWorkbenchProjectStore.setState({
      activeScopeKey: 'server-a|user-a',
      projects: [projectA],
      currentProjectId: PROJECT_A,
      phase: 'ready',
    })
    apiMocks.listProjects.mockReturnValue(nextList.promise)
    apiMocks.getContext.mockReturnValue(nextContext.promise)

    const pending = useWorkbenchProjectStore.getState().hydrate('server-a|user-b')

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      activeScopeKey: 'server-a|user-b',
      projects: [],
      currentProjectId: null,
      phase: 'loading',
    })
    nextList.resolve({ items: [projectB] })
    nextContext.resolve({ project: projectB, updatedAt: 'new', etag: '"new"' })
    await pending
  })

  it('强制 hydration 发现其他标签页切换项目时推进 generation', async () => {
    useWorkbenchProjectStore.setState({
      activeScopeKey: 'server-a|user-a',
      projects: [projectA, projectB],
      currentProjectId: PROJECT_A,
      switchGeneration: 8,
      phase: 'ready',
    })
    apiMocks.listProjects.mockResolvedValue({ items: [projectA, projectB] })
    apiMocks.getContext.mockResolvedValue({ project: projectB, updatedAt: 'new', etag: '"new"' })

    await useWorkbenchProjectStore.getState().hydrate('server-a|user-a', { force: true })

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      currentProjectId: PROJECT_B,
      switchGeneration: 9,
    })
  })

  it('服务器切换 reset 同时清空项目与 runtime 状态', () => {
    useWorkbenchProjectStore.setState({
      projects: [projectA],
      currentProjectId: PROJECT_A,
      phase: 'ready',
    })
    useWorkbenchRuntimeStore.getState().activateProject(PROJECT_A, 1)

    useWorkbenchProjectStore.getState().resetForServerChange()

    expect(useWorkbenchProjectStore.getState()).toMatchObject({
      projects: [],
      currentProjectId: null,
      phase: 'idle',
    })
    expect(useWorkbenchRuntimeStore.getState().projects).toEqual({})
  })
})
