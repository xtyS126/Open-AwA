import { describe, expect, it } from 'vitest'
import type { ToolEventMeta } from '@/features/chat/types'
import {
  applySubagentMessage,
  applySubagentStart,
  applySubagentStop,
  applyToolUpdate,
  createEmptyExecutionMeta,
  getVisibleSubagentTools,
  normalizeTaskStatus,
  SUBAGENT_LOG_LIMIT,
} from '@/features/chat/utils/executionMeta'

describe('executionMeta', () => {
  it('将 done 识别为已完成状态', () => {
    expect(normalizeTaskStatus('done')).toBe('completed')
  })

  it('兼容 result 字段并自动提取工具摘要', () => {
    const meta = applyToolUpdate(createEmptyExecutionMeta(), {
      id: 'tool-1',
      kind: 'plugin',
      name: 'hello-world/say_hello',
      status: 'done',
      result: {
        message: 'Hello, Open-AwA!',
      },
    })

    expect(meta.toolEvents).toHaveLength(1)
    expect(meta.toolEvents[0].status).toBe('completed')
    expect(meta.toolEvents[0].detail).toBe('Hello, Open-AwA!')
    expect(meta.toolEvents[0].output).toEqual({
      message: 'Hello, Open-AwA!',
    })
  })

  it('为子代理持续追加日志并在超长时截断头部', () => {
    let meta = applySubagentStart(createEmptyExecutionMeta(), {
      agentId: 'agt-1',
      agentType: 'planner',
      description: '开始规划',
    })

    meta = applySubagentMessage(meta, {
      agentId: 'agt-1',
      agentType: 'planner',
      message: 'A'.repeat(SUBAGENT_LOG_LIMIT + 128),
    })

    expect(meta.toolEvents).toHaveLength(1)
    expect(meta.toolEvents[0].subagent?.truncated).toBe(true)
    expect(meta.toolEvents[0].subagent?.logs.startsWith('[日志过长，已截断]')).toBe(true)
  })

  it('将 completed 但带 Error 前缀摘要的子代理识别为失败', () => {
    const meta = applySubagentStop(createEmptyExecutionMeta(), {
      agentId: 'agt-2',
      agentType: 'coder',
      state: 'completed',
      summary: 'Error: model unavailable',
    })

    expect(meta.toolEvents[0].status).toBe('error')
    expect(meta.toolEvents[0].subagent?.exitCode).toBe(1)
    expect(meta.toolEvents[0].subagent?.errorText).toContain('model unavailable')
  })

  it('在超过 20 个子代理容器时隐藏最早完成的容器', () => {
    let meta = createEmptyExecutionMeta()

    for (let index = 0; index < 21; index += 1) {
      const agentId = `agt-${index}`
      meta = applySubagentStart(meta, {
        agentId,
        agentType: 'worker',
        description: `worker ${index}`,
      })
      meta = applySubagentStop(meta, {
        agentId,
        agentType: 'worker',
        state: 'completed',
        summary: `完成 ${index}`,
      })
    }

    const visibleTools = getVisibleSubagentTools(meta.toolEvents)
    expect(visibleTools).toHaveLength(20)
    const hiddenTool = meta.toolEvents.find((tool: ToolEventMeta) => tool.id === 'agt-0')
    expect(hiddenTool?.subagent?.visible).toBe(false)
  })
})
