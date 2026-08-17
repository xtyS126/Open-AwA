import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workbenchPreviewApi } from '@/features/workbench/workbenchPreviewApi'

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'

const apiMocks = vi.hoisted(() => ({
  post: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  default: {
    post: apiMocks.post,
    delete: apiMocks.delete,
  },
}))

describe('workbenchPreviewApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('创建 HTTP 预览租约时只提交会话身份与局部端口', async () => {
    apiMocks.post.mockResolvedValue({
      data: {
        preview_id: 'preview-a',
        project_id: PROJECT_ID,
        session_kind: 'terminal',
        session_id: 'terminal-a',
        port: 5173,
        expires_at: '2026-08-15T12:15:00Z',
      },
    })

    await expect(workbenchPreviewApi.create(PROJECT_ID, {
      sessionKind: 'terminal',
      sessionId: 'terminal-a',
      port: 5173,
    })).resolves.toEqual({
      previewId: 'preview-a',
      projectId: PROJECT_ID,
      sessionKind: 'terminal',
      sessionId: 'terminal-a',
      expiresAt: '2026-08-15T12:15:00Z',
    })
    expect(apiMocks.post).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}/previews`,
      {
        session_kind: 'terminal',
        session_id: 'terminal-a',
        port: 5173,
      },
    )
  })

  it('续租与撤销始终带 project_id 和 preview_id', async () => {
    apiMocks.post.mockResolvedValue({
      data: {
        preview_id: 'preview-a',
        project_id: PROJECT_ID,
        session_kind: 'terminal',
        session_id: 'terminal-a',
        port: 5173,
        expires_at: '2026-08-15T12:30:00Z',
      },
    })
    apiMocks.delete.mockResolvedValue({ data: undefined })

    await workbenchPreviewApi.renew(PROJECT_ID, 'preview-a')
    await workbenchPreviewApi.revoke(PROJECT_ID, 'preview-a')

    expect(apiMocks.post).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}/previews/preview-a/renew`,
    )
    expect(apiMocks.delete).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}/previews/preview-a`,
    )
  })
})
