import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '@/shared/api/api'
import { codingApi } from '@/features/coding/codingApi'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'

vi.mock('@/shared/api/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const PROJECT_ID = asWorkbenchProjectId('project-123')

describe('codingApi 项目标识契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({ data: {} })
    vi.mocked(api.post).mockResolvedValue({ data: {} })
  })

  it.each([
    ['getTree', () => codingApi.getTree(PROJECT_ID, 'src')],
    ['listDir', () => codingApi.listDir(PROJECT_ID, 'src')],
    ['gitStatus', () => codingApi.gitStatus(PROJECT_ID)],
    ['gitDiff', () => codingApi.gitDiff(PROJECT_ID, 'src/app.ts', false)],
    ['gitLog', () => codingApi.gitLog(PROJECT_ID, 10)],
    ['gitBranches', () => codingApi.gitBranches(PROJECT_ID)],
    ['searchDefinitions', () => codingApi.searchDefinitions(PROJECT_ID, 'App')],
    ['searchReferences', () => codingApi.searchReferences(PROJECT_ID, 'App')],
    ['getStructure', () => codingApi.getStructure(PROJECT_ID, 'src/app.ts')],
    ['getLSPDiagnostics', () => codingApi.getLSPDiagnostics(PROJECT_ID, 'src/app.ts')],
    ['getLSPSymbols', () => codingApi.getLSPSymbols(PROJECT_ID, 'src/app.ts')],
  ])('%s 的查询参数只发送 project_id', async (_name, invoke) => {
    await invoke()

    const config = vi.mocked(api.get).mock.calls.at(-1)?.[1]
    expect(config?.params).toMatchObject({ project_id: PROJECT_ID })
    expect(config?.params).not.toHaveProperty('project_dir')
  })

  it.each([
    ['readFile', () => codingApi.readFile(PROJECT_ID, 'src/app.ts')],
    ['writeFile', () => codingApi.writeFile(PROJECT_ID, 'src/app.ts', 'next')],
    ['searchFiles', () => codingApi.searchFiles(PROJECT_ID, '*.ts', 'src')],
    ['gitCommit', () => codingApi.gitCommit(PROJECT_ID, 'test commit', ['src/app.ts'])],
    ['searchPattern', () => codingApi.searchPattern(PROJECT_ID, 'class $A')],
    ['getLSPCompletions', () => codingApi.getLSPCompletions(PROJECT_ID, 'src/app.ts', 1, 2)],
    ['getLSPHover', () => codingApi.getLSPHover(PROJECT_ID, 'src/app.ts', 1, 2)],
  ])('%s 的请求体只发送 project_id', async (_name, invoke) => {
    await invoke()

    const body = vi.mocked(api.post).mock.calls.at(-1)?.[1]
    expect(body).toMatchObject({ project_id: PROJECT_ID })
    expect(body).not.toHaveProperty('project_dir')
  })
})
