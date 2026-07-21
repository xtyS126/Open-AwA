import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'
import type { AssistantExecutionMeta, ChatMessage } from '@/features/chat/types'
import { findLatestActiveExecution, hasPendingPanelActivity } from '@/features/chat/hooks/useTaskPanelState'
import { createEmptyExecutionMeta } from '@/features/chat/utils/executionMeta'

function buildMessage(id: string, role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id,
    role,
    content,
    timestamp: new Date('2026-05-16T00:00:00Z'),
  }
}

function buildMeta(partial?: Partial<AssistantExecutionMeta>): AssistantExecutionMeta {
  return {
    ...createEmptyExecutionMeta(),
    ...partial,
    steps: partial?.steps || [],
    toolEvents: partial?.toolEvents || [],
  }
}

describe('useTaskPanelState helpers', () => {
  it('prefers the currently streaming assistant execution', () => {
    const messages = [
      buildMessage('user-1', 'user', 'hello'),
      buildMessage('assistant-1', 'assistant', 'world'),
    ]
    const messageMeta = {
      'assistant-1': buildMeta({
        steps: [{ step: 1, action: 'search', status: 'running' }],
      }),
    }

    const activeExecution = findLatestActiveExecution(messages, messageMeta, 'assistant-1')

    expect(activeExecution).not.toBeNull()
    expect(activeExecution?.isStreaming).toBe(true)
    expect(activeExecution?.meta.steps).toHaveLength(1)
  })

  it('falls back to the latest assistant execution metadata when not streaming', () => {
    const messages = [
      buildMessage('assistant-old', 'assistant', 'old'),
      buildMessage('assistant-new', 'assistant', 'new'),
    ]
    const messageMeta = {
      'assistant-old': buildMeta({
        steps: [{ step: 1, action: 'plan', status: 'completed' }],
      }),
      'assistant-new': buildMeta({
        toolEvents: [{ id: 'tool-1', kind: 'task', name: 'run', status: 'pending' }],
      }),
    }

    const activeExecution = findLatestActiveExecution(messages, messageMeta, null)

    expect(activeExecution?.isStreaming).toBe(false)
    expect(activeExecution?.meta.toolEvents[0]?.id).toBe('tool-1')
    expect(hasPendingPanelActivity(activeExecution || null)).toBe(true)
  })

  it('treats streaming without metadata as active work', () => {
    const activeExecution = findLatestActiveExecution([], {}, 'assistant-streaming')

    expect(activeExecution).toEqual({
      meta: createEmptyExecutionMeta(),
      isStreaming: true,
    })
    expect(hasPendingPanelActivity(activeExecution)).toBe(true)
  })
})