import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import type { AssistantExecutionMeta, AssistantMessageSegment } from '@/features/chat/types'
import { createEmptyExecutionMeta } from '@/features/chat/utils/executionMeta'
import { dispatchStructuredStreamEvent } from '@/features/chat/utils/dispatchStructuredStreamEvent'

function createTestContext() {
  let meta: AssistantExecutionMeta = createEmptyExecutionMeta()
  let segments: AssistantMessageSegment[] | undefined = []
  let todoItems: Array<{ id: string; content: string; status: 'pending' | 'in_progress' | 'completed' }> = []
  let todoSummary = ''

  const addToast = vi.fn()
  const clearSubagentAggregationTimer = vi.fn()
  const scheduleSubagentTimeout = vi.fn()
  const syncSubagentRuntime = vi.fn()
  const clearSubagentTimeout = vi.fn()
  const clearSubagentSyncTimer = vi.fn()
  const scheduleSubagentAggregation = vi.fn()
  const dispatchUsageUpdated = vi.fn()

  return {
    getMeta: () => meta,
    getSegments: () => segments,
    getTodoItems: () => todoItems,
    getTodoSummary: () => todoSummary,
    addToast,
    clearSubagentAggregationTimer,
    scheduleSubagentTimeout,
    syncSubagentRuntime,
    clearSubagentTimeout,
    clearSubagentSyncTimer,
    scheduleSubagentAggregation,
    dispatchUsageUpdated,
    options: {
      assistantMessageId: 'assistant-1',
      messageMeta: {},
      addToast,
      updateAssistantMeta: (_messageId: string, updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta) => {
        meta = updater(meta)
      },
      updateAssistantSegments: (
        _messageId: string,
        updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[],
      ) => {
        segments = updater(segments)
      },
      clearSubagentAggregationTimer,
      scheduleSubagentTimeout,
      syncSubagentRuntime,
      clearSubagentTimeout,
      clearSubagentSyncTimer,
      scheduleSubagentAggregation,
      setTodoItems: (items: Array<{ id: string; content: string; status: 'pending' | 'in_progress' | 'completed' }>) => {
        todoItems = items
      },
      setTodoSummary: (summary: string) => {
        todoSummary = summary
      },
      dispatchUsageUpdated,
      getNow: () => 123456,
    },
  }
}

describe('dispatchStructuredStreamEvent', () => {
  it('handles notification and todo update events', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({ type: 'notification', body: '任务已完成' }, context.options)
    dispatchStructuredStreamEvent({
      type: 'todo_update',
      todos: [{ id: '1', content: '检查结果', status: 'in_progress' }],
      summary: '处理中',
    }, context.options)

    expect(context.addToast).toHaveBeenCalledWith('任务已完成', 'info')
    expect(context.getTodoItems()).toEqual([{ id: '1', content: '检查结果', status: 'in_progress' }])
    expect(context.getTodoSummary()).toBe('处理中')
  })

  it('updates usage metadata and dispatches billing refresh', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'usage',
      usage: {
        call_id: 'call-1',
        provider: 'openai',
        model: 'gpt-4o-mini',
        input_tokens: 12,
        output_tokens: 6,
        total_cost: 0.01,
        currency: 'USD',
      },
    }, context.options)

    expect(context.getMeta().usage?.call_id).toBe('call-1')
    expect(context.dispatchUsageUpdated).toHaveBeenCalledWith({
      callId: 'call-1',
      provider: 'openai',
      model: 'gpt-4o-mini',
    })
  })

  it('starts background subagents and schedules runtime sync', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'subagent_start',
      agent_id: 'agt-1',
      agent_type: 'planner',
      description: '规划任务',
      run_mode: 'background',
    }, context.options)

    expect(context.getMeta().toolEvents[0]?.id).toBe('agt-1')
    expect(context.clearSubagentAggregationTimer).toHaveBeenCalledWith('assistant-1')
    expect(context.scheduleSubagentTimeout).toHaveBeenCalledWith('assistant-1', 'agt-1', 'planner')
    expect(context.syncSubagentRuntime).toHaveBeenCalledWith('assistant-1', 'agt-1', 'planner')
  })

  it('handles plan event with intent and steps', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'plan',
      plan: {
        intent: 'analyse',
        steps: [{ step: 1, action: 'llm_chat', status: 'running', purpose: '分析用户问题' }],
      },
    }, context.options)

    expect(context.getMeta().intent).toBe('analyse')
    expect(context.getMeta().steps).toHaveLength(1)
    expect(context.getMeta().steps[0]?.purpose).toBe('分析用户问题')
    expect(context.getSegments()).toHaveLength(1)
  })

  it('handles result event with tool output patching', () => {
    const context = createTestContext()

    // 先创建 tool 事件注册工具
    dispatchStructuredStreamEvent({
      type: 'tool',
      tool: { id: 'tool-xyz', kind: 'mcp', name: 'search', status: 'running' },
    }, context.options)

    // result 事件带 tool_id 输出，修补已有工具
    dispatchStructuredStreamEvent({
      type: 'result',
      result: { tool_id: 'tool-xyz', output: '工具输出结果' },
    }, context.options)

    const toolEvents = context.getMeta().toolEvents
    const found = toolEvents.find((t) => t.id === 'tool-xyz')
    expect(found?.output).toBe('工具输出结果')
    expect(found?.status).toBe('completed')
  })

  it('handles task event adding a step', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'task',
      task: { step: 1, action: 'tool_call', status: 'running', purpose: '调用工具' },
    }, context.options)

    expect(context.getMeta().steps).toHaveLength(1)
    expect(context.getSegments()).toHaveLength(1)
    const segment = context.getSegments()[0]
    expect(segment?.kind).toBe('thought')
  })

  it('handles tool event with input normalization', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'tool',
      tool: { id: 'tool-abc', kind: 'mcp', name: 'filesystem/read', arguments: { path: '/test.txt' } },
    }, context.options)

    expect(context.getMeta().toolEvents).toHaveLength(1)
    expect(context.getMeta().toolEvents[0]?.id).toBe('tool-abc')
    const segment = context.getSegments()[0]
    if (segment?.kind === 'thought') {
      expect(segment.toolEvents).toHaveLength(1)
    }
  })

  it('handles subagent_stop and cleans up timers', () => {
    const context = createTestContext()

    dispatchStructuredStreamEvent({
      type: 'subagent_stop',
      agent_id: 'agt-1',
      agent_type: 'planner',
      state: 'completed',
      summary: '规划完成',
    }, context.options)

    expect(context.clearSubagentTimeout).toHaveBeenCalledWith('agt-1')
    expect(context.clearSubagentSyncTimer).toHaveBeenCalledWith('agt-1')
    expect(context.scheduleSubagentAggregation).toHaveBeenCalledWith('assistant-1')
  })

  it('ignores unknown event types without throwing', () => {
    const context = createTestContext()

    expect(() => {
      dispatchStructuredStreamEvent({ type: 'unknown_event', data: 'test' }, context.options)
    }).not.toThrow()
  })
})