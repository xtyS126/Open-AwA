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
})