import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  asWorkbenchProjectId,
  type WorkbenchProjectSummary,
} from '@/features/workbench/workbenchTypes'
import { workbenchApi } from '@/features/workbench/workbenchApi'

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  api: apiMocks,
}))

const PROJECT_ID = asWorkbenchProjectId('11111111-1111-4111-8111-111111111111')

const serverProject = {
  id: PROJECT_ID,
  display_name: 'Open-AwA',
  is_enabled: true,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  last_opened_at: null,
  registered_root: 'D:\\private',
  canonical_root: 'd:\\private',
  resolved_root: 'D:\\private',
}

function collectKeys(value: unknown, result = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    value.forEach((item) => collectKeys(item, result))
    return result
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, item]) => {
      result.add(key)
      collectKeys(item, result)
    })
  }
  return result
}

describe('workbenchApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('普通响应只映射项目摘要白名单字段', async () => {
    apiMocks.get
      .mockResolvedValueOnce({ data: { items: [serverProject] }, headers: {} })
      .mockResolvedValueOnce({
        data: { project: serverProject, updated_at: '2026-08-12T00:00:00Z' },
        headers: { etag: '"context-v1"' },
      })

    const list = await workbenchApi.listProjects()
    const context = await workbenchApi.getContext()

    const expected: WorkbenchProjectSummary = {
      id: PROJECT_ID,
      displayName: 'Open-AwA',
      isEnabled: true,
      createdAt: '2026-08-12T00:00:00Z',
      updatedAt: '2026-08-12T00:00:00Z',
      lastOpenedAt: null,
    }
    expect(list.items).toEqual([expected])
    expect(context).toEqual({
      project: expected,
      updatedAt: '2026-08-12T00:00:00Z',
      etag: '"context-v1"',
    })
    expect(collectKeys({ list, context })).not.toContain('registered_root')
    expect(collectKeys({ list, context })).not.toContain('canonical_root')
    expect(collectKeys({ list, context })).not.toContain('resolved_root')
  })

  it('登记项目是唯一发送 root 的调用', async () => {
    apiMocks.post.mockResolvedValue({ data: serverProject, headers: {} })
    apiMocks.patch.mockResolvedValue({ data: serverProject, headers: {} })
    apiMocks.delete.mockResolvedValue({ data: undefined, headers: {} })

    await workbenchApi.createProject({ displayName: 'Open-AwA', root: 'D:\\代码\\Open-AwA' })
    await workbenchApi.updateProject(PROJECT_ID, { displayName: '主仓库', isEnabled: false })
    await workbenchApi.deleteProject(PROJECT_ID)

    expect(apiMocks.post).toHaveBeenCalledWith('/workbench/projects', {
      display_name: 'Open-AwA',
      root: 'D:\\代码\\Open-AwA',
    })
    expect(apiMocks.patch).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}`,
      { display_name: '主仓库', is_enabled: false },
    )
    const nonCreateKeys = collectKeys([
      apiMocks.patch.mock.calls,
      apiMocks.delete.mock.calls,
    ])
    expect(nonCreateKeys).not.toContain('root')
    expect(nonCreateKeys).not.toContain('project_dir')
    expect(nonCreateKeys).not.toContain('cwd')
    expect(nonCreateKeys).not.toContain('resolved_root')
  })

  it('更新上下文只发送品牌化 project_id 并携带 If-Match', async () => {
    apiMocks.patch.mockResolvedValue({
      data: { project: serverProject, updated_at: '2026-08-12T00:00:01Z' },
      headers: { etag: '"context-v2"' },
    })

    await workbenchApi.patchContext(PROJECT_ID, '"context-v1"')

    expect(apiMocks.patch).toHaveBeenCalledWith(
      '/workbench/context',
      { project_id: PROJECT_ID },
      { headers: { 'If-Match': '"context-v1"' } },
    )
    const keys = collectKeys(apiMocks.patch.mock.calls)
    expect(keys).not.toContain('project_dir')
    expect(keys).not.toContain('projectCwd')
    expect(keys).not.toContain('cwd')
    expect(keys).not.toContain('resolved_root')
  })
})
