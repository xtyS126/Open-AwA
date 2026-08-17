import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import api from '@/shared/api/api'
import {
  createPtySession,
  createSession,
  type PTYCreateResponse,
  type PTYSessionInfo,
  type TerminalSession,
} from '@/shared/api/terminalApi'

vi.mock('@/shared/api/api', () => ({
  default: {
    post: vi.fn(),
  },
}))

const PROJECT_ID = 'project-123'

describe('terminalApi 项目标识契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.post).mockResolvedValue({ data: {} })
  })

  it('普通终端创建查询只发送 project_id', async () => {
    await createSession(PROJECT_ID)

    expect(api.post).toHaveBeenCalledWith('/terminal/sessions', null, {
      params: { project_id: PROJECT_ID },
    })
  })

  it('PTY 创建请求只用 project_id 表达项目上下文', async () => {
    await createPtySession({
      projectId: PROJECT_ID,
      cols: 100,
      rows: 40,
      command: ['pwsh'],
    })

    const body = vi.mocked(api.post).mock.calls.at(-1)?.[1]
    expect(body).toEqual({
      project_id: PROJECT_ID,
      cols: 100,
      rows: 40,
      command: ['pwsh'],
    })
    expect(body).not.toHaveProperty('cwd')
    expect(body).not.toHaveProperty('projectCwd')
    expect(body).not.toHaveProperty('project_dir')
    expect(body).not.toHaveProperty('projectDir')
  })

  it('终端响应类型只公开 project_id，不公开服务端路径', () => {
    expectTypeOf<TerminalSession>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<TerminalSession>().not.toHaveProperty('cwd')
    expectTypeOf<TerminalSession>().not.toHaveProperty('root')
    expectTypeOf<PTYSessionInfo>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<PTYSessionInfo>().not.toHaveProperty('cwd')
    expectTypeOf<PTYCreateResponse>().toHaveProperty('project_id').toEqualTypeOf<string>()
    expectTypeOf<PTYCreateResponse>().not.toHaveProperty('cwd')
  })
})
