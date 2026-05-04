import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
  sharedApiMock,
  sharedApiModuleMock,
} = vi.hoisted(() => {
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  }

  return {
    sharedApiMock: apiMock,
    sharedApiModuleMock: {
      sharedApi: apiMock,
    },
  }
})

vi.mock('@/shared/api/api', () => sharedApiModuleMock)

import {
  claimTask,
  createTeam,
  stopAgent,
} from '@/shared/api/taskRuntimeApi'
import { subagentAPI, toolsAPI } from '@/shared/api/toolsApi'

describe('task 相关 API 的 CSRF 兼容性', () => {
  beforeEach(() => {
    sharedApiMock.get.mockReset()
    sharedApiMock.post.mockReset()
    sharedApiMock.patch.mockReset()
    sharedApiMock.delete.mockReset()

    sharedApiMock.get.mockResolvedValue({ data: {} })
    sharedApiMock.post.mockResolvedValue({ data: {} })
    sharedApiMock.patch.mockResolvedValue({ data: {} })
    sharedApiMock.delete.mockResolvedValue({ data: {} })
  })

  it('taskRuntimeApi 的写操作复用 sharedApi', async () => {
    await stopAgent('agent-1')
    await claimTask('task-1', 'agent-2')
    await createTeam({ lead_agent_id: 'agent-3', name: '团队A' })

    expect(sharedApiMock.post).toHaveBeenNthCalledWith(1, '/task-runtime/agents/agent-1/stop')
    expect(sharedApiMock.post).toHaveBeenNthCalledWith(2, '/task-runtime/tasks/task-1/claim', null, {
      params: { agent_id: 'agent-2' },
    })
    expect(sharedApiMock.post).toHaveBeenNthCalledWith(3, '/task-runtime/teams', null, {
      params: { lead_agent_id: 'agent-3', name: '团队A' },
    })
  })

  it('toolsAPI 的写操作复用 sharedApi', async () => {
    await toolsAPI.fileWrite('D:/workspace/demo.txt', 'content')
    await toolsAPI.terminalRun('dir', 'D:/workspace', 10)

    expect(sharedApiMock.post).toHaveBeenNthCalledWith(1, '/tools/file/write', {
      path: 'D:/workspace/demo.txt',
      content: 'content',
    })
    expect(sharedApiMock.post).toHaveBeenNthCalledWith(2, '/tools/terminal/run', {
      command: 'dir',
      working_dir: 'D:/workspace',
      timeout: 10,
    })
  })

  it('subagentAPI 的写操作复用 sharedApi', async () => {
    await subagentAPI.runGraph('planner', { task_id: 'task-1' }, [{ role: 'user', content: 'start' }])
    await subagentAPI.runParallel(['planner', 'coder'], { task_id: 'task-2' }, 180)

    expect(sharedApiMock.post).toHaveBeenNthCalledWith(1, '/subagents/run/graph', {
      graph_name: 'planner',
      context: { task_id: 'task-1' },
      messages: [{ role: 'user', content: 'start' }],
    })
    expect(sharedApiMock.post).toHaveBeenNthCalledWith(2, '/subagents/run/parallel', {
      agent_names: ['planner', 'coder'],
      context: { task_id: 'task-2' },
      timeout: 180,
    })
  })
})
