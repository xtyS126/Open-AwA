import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import api from '@/shared/api/api'
import {
  cancelTurn,
  closeSession,
  createPromptRequest,
  createSession,
  getOpenCodeStatus,
  installOpenCode,
  listSessions,
  respondPermission,
  type AcpCreateSessionResponse,
  type AcpSession,
  type OpenCodeStatus,
} from '@/shared/api/acpApi'

vi.mock('@/shared/api/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

const PROJECT_ID = 'project-123'
const SESSION_ID = 'session-456'

describe('acpApi 项目标识契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({ data: {} })
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    vi.mocked(api.delete).mockResolvedValue({ data: {} })
  })

  it('创建会话只发送 project_id 并保留 AbortSignal', async () => {
    const controller = new AbortController()

    await createSession(PROJECT_ID, 'codex', controller.signal)

    expect(api.post).toHaveBeenCalledWith(
      '/acp/sessions',
      { agent: 'codex', project_id: PROJECT_ID },
      { signal: controller.signal },
    )
  })

  it('会话列表只用 project_id 过滤项目', async () => {
    await listSessions(PROJECT_ID, 'codex')

    expect(api.get).toHaveBeenCalledWith('/acp/sessions', {
      params: { project_id: PROJECT_ID, agent: 'codex' },
    })
  })

  it('OpenCode 状态查询只发送 project_id', async () => {
    await getOpenCodeStatus(PROJECT_ID)

    expect(api.get).toHaveBeenCalledWith('/acp/opencode/status', {
      params: { project_id: PROJECT_ID },
    })
  })

  it('OpenCode 安装请求只发送 project_id 与确认字段', async () => {
    await installOpenCode(PROJECT_ID)

    expect(api.post).toHaveBeenCalledWith('/acp/opencode/install', {
      project_id: PROJECT_ID,
      confirm_install: true,
    })
  })

  it('SSE prompt 请求体只包含 prompt 与 project_id', () => {
    const request = createPromptRequest(PROJECT_ID, '检查当前改动')

    expect(request).toEqual({ prompt: '检查当前改动', project_id: PROJECT_ID })
    expect(request).not.toHaveProperty('cwd')
    expect(request).not.toHaveProperty('projectCwd')
    expect(request).not.toHaveProperty('project_dir')
    expect(request).not.toHaveProperty('projectDir')
  })

  it('权限响应只发送 option_id 与 project_id', async () => {
    await respondPermission(PROJECT_ID, SESSION_ID, 'allow_once')

    expect(api.post).toHaveBeenCalledWith(`/acp/sessions/${SESSION_ID}/permission`, {
      option_id: 'allow_once',
      project_id: PROJECT_ID,
    })
  })

  it('取消请求通过查询参数发送 project_id', async () => {
    await cancelTurn(PROJECT_ID, SESSION_ID)

    expect(api.post).toHaveBeenCalledWith(
      `/acp/sessions/${SESSION_ID}/cancel`,
      null,
      { params: { project_id: PROJECT_ID } },
    )
  })

  it('关闭请求通过查询参数发送 project_id', async () => {
    await closeSession(PROJECT_ID, SESSION_ID)

    expect(api.delete).toHaveBeenCalledWith(`/acp/sessions/${SESSION_ID}`, {
      params: { project_id: PROJECT_ID },
    })
  })

  it('普通响应类型只公开 project_id，不公开服务端路径', () => {
    expectTypeOf<AcpSession>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<AcpSession>().not.toHaveProperty('cwd')
    expectTypeOf<AcpSession>().not.toHaveProperty('root')
    expectTypeOf<AcpCreateSessionResponse>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<AcpCreateSessionResponse>().not.toHaveProperty('cwd')
    expectTypeOf<OpenCodeStatus>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<OpenCodeStatus>().not.toHaveProperty('cwd')
  })
})
