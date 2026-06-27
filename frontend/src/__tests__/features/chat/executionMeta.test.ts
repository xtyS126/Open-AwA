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

  it('在结构化子代理日志前自动补换行分隔', () => {
    let meta = applySubagentStart(createEmptyExecutionMeta(), {
      agentId: 'agt-structured-1',
      agentType: 'planner',
      description: '开始规划',
    })

    meta = applySubagentMessage(meta, {
      agentId: 'agt-structured-1',
      agentType: 'planner',
      message: '[工具] builtin_list_files: running',
    })

    meta = applySubagentMessage(meta, {
      agentId: 'agt-structured-1',
      agentType: 'planner',
      message: '[工具] builtin_list_files: 工具调用完成',
    })

    expect(meta.toolEvents[0].subagent?.logs).toBe(
      '开始规划\n[工具] builtin_list_files: running\n[工具] builtin_list_files: 工具调用完成'
    )
  })

  it('依据 state 字段判定失败，不再因 summary 以 Error 开头而误判 completed 子代理', () => {
    // state=completed 但 summary 以 "Error:" 开头（如子代理讨论错误处理），
    // 不应被误判为失败——仅依据 state 字段判断
    const meta = applySubagentStop(createEmptyExecutionMeta(), {
      agentId: 'agt-2',
      agentType: 'coder',
      state: 'completed',
      summary: 'Error: model unavailable 这个问题需要处理',
    })

    expect(meta.toolEvents[0].status).toBe('completed')
    expect(meta.toolEvents[0].subagent?.exitCode).toBe(0)
    expect(meta.toolEvents[0].subagent?.errorText).toBeUndefined()
  })

  it('state 为 failed 时识别为失败', () => {
    const meta = applySubagentStop(createEmptyExecutionMeta(), {
      agentId: 'agt-3',
      agentType: 'coder',
      state: 'failed',
      summary: 'KeyError: missing config',
    })

    expect(meta.toolEvents[0].status).toBe('error')
    expect(meta.toolEvents[0].subagent?.exitCode).toBe(1)
    expect(meta.toolEvents[0].subagent?.errorText).toContain('KeyError')
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
