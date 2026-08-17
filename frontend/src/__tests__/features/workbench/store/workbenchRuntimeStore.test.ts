import { beforeEach, describe, expect, it } from 'vitest'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'

const PROJECT_A = asWorkbenchProjectId('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
const PROJECT_B = asWorkbenchProjectId('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')

describe('workbenchRuntimeStore', () => {
  beforeEach(() => {
    useWorkbenchRuntimeStore.getState().resetAll()
  })

  it('按 project_id 隔离 ACP 与预览状态', () => {
    const store = useWorkbenchRuntimeStore.getState()
    store.activateProject(PROJECT_A, 1)
    store.activateProject(PROJECT_B, 1)
    store.setSelectedAgent(PROJECT_A, 1, 'codex')
    store.setSelectedSession(PROJECT_A, 1, 'session-a')
    store.setPreviewIntent(PROJECT_A, 1, { kind: 'file', relativePath: 'README.md' })

    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A]).toMatchObject({
      selectedAgentId: 'codex',
      selectedSessionId: 'session-a',
      previewIntent: { kind: 'file', relativePath: 'README.md' },
    })
    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_B]).toMatchObject({
      selectedAgentId: null,
      selectedSessionId: null,
      previewIntent: { kind: 'none' },
    })
  })

  it('拒绝旧 generation 的异步状态写回', () => {
    const store = useWorkbenchRuntimeStore.getState()
    store.activateProject(PROJECT_A, 4)
    store.activateProject(PROJECT_A, 3)
    store.setTerminalBinding(PROJECT_A, 3, { kind: 'attached', sessionId: 'stale' })
    store.setPreviewIntent(PROJECT_A, 3, { kind: 'web', previewId: 'old-preview' })

    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A]).toMatchObject({
      generation: 4,
      terminalBinding: { kind: 'none' },
      previewIntent: { kind: 'none' },
    })
  })

  it('预览 runtime 只保存受限 previewId，不保存端口', () => {
    const store = useWorkbenchRuntimeStore.getState()
    store.activateProject(PROJECT_A, 1)
    store.setPreviewIntent(PROJECT_A, 1, { kind: 'web', previewId: 'preview-a' })

    const serialized = JSON.stringify(useWorkbenchRuntimeStore.getState().projects[PROJECT_A])
    expect(serialized).toContain('preview-a')
    expect(serialized).not.toMatch(/port|5173/i)
  })

  it('进入更高 generation 时保留项目偏好但清空旧代资源绑定', () => {
    const store = useWorkbenchRuntimeStore.getState()
    store.activateProject(PROJECT_A, 1)
    store.setSelectedAgent(PROJECT_A, 1, 'codex')
    store.setTerminalBinding(PROJECT_A, 1, { kind: 'attached', sessionId: 'terminal-old' })
    store.setPreviewIntent(PROJECT_A, 1, { kind: 'web', previewId: 'preview-old' })

    store.activateProject(PROJECT_A, 2)

    expect(useWorkbenchRuntimeStore.getState().projects[PROJECT_A]).toMatchObject({
      generation: 2,
      selectedAgentId: 'codex',
      terminalBinding: { kind: 'none' },
      previewIntent: { kind: 'none' },
    })
  })
})
