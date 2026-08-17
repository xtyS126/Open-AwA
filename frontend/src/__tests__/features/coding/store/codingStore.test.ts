import { beforeEach, describe, expect, it, vi } from 'vitest'
import { codingApi } from '@/features/coding/codingApi'
import { useCodingStore } from '@/features/coding/store/codingStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

vi.mock('@/features/coding/codingApi', () => ({
  codingApi: {
    writeFile: vi.fn(),
  },
}))

const PROJECT_A = asWorkbenchProjectId('project-a')
const PROJECT_B = asWorkbenchProjectId('project-b')

describe('codingStore 项目切换事务', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useCodingStore.setState({
      projectId: PROJECT_A,
      projectGeneration: 4,
      switchingToProjectId: null,
      projectSnapshots: {},
      activePanel: 'editor',
      fileTree: {
        name: 'project-a',
        type: 'directory',
        path: '',
      },
      openFiles: [{
        path: 'src/app.ts',
        name: 'app.ts',
        content: 'changed',
        isDirty: true,
        language: 'typescript',
      }],
      activeFilePath: 'src/app.ts',
      gitChanges: [{ status: 'M', file: 'src/app.ts' }],
      gitBranch: 'main',
      diffMode: true,
      editorFontSize: 18,
      ccModeEnabled: true,
    })
    vi.mocked(codingApi.writeFile).mockResolvedValue({
      path: 'src/app.ts',
      written: true,
      size: 7,
    })
  })

  it('preflight 发现 dirty buffer 时返回相对路径阻断项', () => {
    expect(useCodingStore.getState().preflightProjectSwitch(PROJECT_B)).toEqual({
      dirtyPaths: ['src/app.ts'],
    })
  })

  it('dirty buffer 未提供决策时不进入准备阶段', async () => {
    await expect(useCodingStore.getState().prepareProjectSwitch(PROJECT_B))
      .rejects.toThrow('当前项目仍有未处理的 dirty 文件')
    expect(codingApi.writeFile).not.toHaveBeenCalled()
    expect(useCodingStore.getState().openFiles[0].content).toBe('changed')
  })

  it('保存准备会先写入 dirty 文件，显式 commit 后才提交本地项目', async () => {
    const prepared = await useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'save')

    expect(codingApi.writeFile).toHaveBeenCalledWith(PROJECT_A, 'src/app.ts', 'changed')
    expect(useCodingStore.getState().projectId).toBe(PROJECT_A)

    await prepared.commit(5)
    expect(useCodingStore.getState().projectId).toBe(PROJECT_B)
    expect(useCodingStore.getState().projectSnapshots[PROJECT_A].openFiles[0].isDirty).toBe(false)
  })

  it('Workbench 在 PATCH 完成时抢先广播目标项目也不应中断 Coding 本地提交', async () => {
    const prepared = await useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'save')
    useCodingStore.getState().syncCommittedProject(PROJECT_B, 5)
    await prepared.commit(5)

    const state = useCodingStore.getState()
    expect(state.projectId).toBe(PROJECT_B)
    expect(state.projectSnapshots[PROJECT_A].openFiles[0]).toMatchObject({
      content: 'changed',
      isDirty: false,
    })
  })

  it('放弃选择不写盘，但按项目 ID 保存包含 dirty 内容的内存快照', async () => {
    const prepared = await useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'discard')
    await prepared.commit(5)

    expect(codingApi.writeFile).not.toHaveBeenCalled()
    expect(useCodingStore.getState().projectSnapshots[PROJECT_A].openFiles[0]).toMatchObject({
      content: 'changed',
      isDirty: true,
    })
  })

  it('保存失败时不进入 staged 状态，并完整保留旧项目 dirty buffer', async () => {
    vi.mocked(codingApi.writeFile).mockRejectedValue(new Error('write failed'))

    await expect(useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'save'))
      .rejects.toThrow('write failed')
    expect(useCodingStore.getState().projectId).toBe(PROJECT_A)
    expect(useCodingStore.getState().switchingToProjectId).toBeNull()
    expect(useCodingStore.getState().openFiles[0]).toMatchObject({ content: 'changed', isDirty: true })
  })

  it('服务端提交失败后 abort 会保留旧项目和编辑内容', async () => {
    const prepared = await useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'discard')
    await prepared.abort?.()
    expect(useCodingStore.getState().projectId).toBe(PROJECT_A)
    expect(useCodingStore.getState().switchingToProjectId).toBeNull()
    expect(useCodingStore.getState().openFiles[0].content).toBe('changed')
    expect(useCodingStore.getState().fileTree?.name).toBe('project-a')
  })

  it('成功切换会恢复目标快照、清空派生状态并保留全局偏好', async () => {
    useCodingStore.setState({
      projectSnapshots: {
        [PROJECT_B]: {
          openFiles: [{
            path: 'README.md',
            name: 'README.md',
            content: 'project b',
            isDirty: false,
            language: 'markdown',
          }],
          activeFilePath: 'README.md',
          activePanel: 'files',
        },
      },
    })

    const prepared = await useCodingStore.getState().prepareProjectSwitch(PROJECT_B, 'discard')
    await prepared.commit(5)

    const state = useCodingStore.getState()
    expect(state.openFiles.map((file) => file.path)).toEqual(['README.md'])
    expect(state.activeFilePath).toBe('README.md')
    expect(state.activePanel).toBe('files')
    expect(state.fileTree).toBeNull()
    expect(state.gitChanges).toEqual([])
    expect(state.gitBranch).toBe('')
    expect(state.diffMode).toBe(false)
    expect(state.editorFontSize).toBe(18)
    expect(state.ccModeEnabled).toBe(true)
  })

  it('旧 generation 的请求上下文不得写回新项目', async () => {
    const oldRequest = useCodingStore.getState().captureRequestContext()
    expect(oldRequest).not.toBeNull()

    useCodingStore.getState().syncCommittedProject(PROJECT_B, 9)

    expect(useCodingStore.getState().isRequestContextCurrent(oldRequest!)).toBe(false)
    expect(useCodingStore.getState().captureRequestContext()).toEqual({
      projectId: PROJECT_B,
      generation: 9,
    })
  })
})
