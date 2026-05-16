import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import type { AssistantExecutionMeta, ChatMessage } from '@/features/chat/types'
import { applyDirectAssistantResponse } from '@/features/chat/utils/applyDirectAssistantResponse'

function createBaseMessage(): ChatMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '',
    timestamp: new Date('2026-01-01T00:00:00.000Z'),
  }
}

function createContext() {
  let message = createBaseMessage()
  let messageMeta: Record<string, AssistantExecutionMeta> = {}
  const addMessage = vi.fn()
  const dispatchUsageUpdated = vi.fn()

  return {
    addMessage,
    dispatchUsageUpdated,
    getMessage: () => message,
    getMessageMeta: () => messageMeta,
    options: {
      assistantMessageId: 'assistant-1',
      addMessage,
      updateMessage: (_messageId: string, updater: (current: ChatMessage) => ChatMessage) => {
        message = updater(message)
      },
      setMessageMeta: (updater: (current: Record<string, AssistantExecutionMeta>) => Record<string, AssistantExecutionMeta>) => {
        messageMeta = updater(messageMeta)
      },
      sanitizeDisplayedError: (value: string) => value.trim(),
      dispatchUsageUpdated,
    },
  }
}

describe('applyDirectAssistantResponse', () => {
  it('writes assistant text and execution metadata', () => {
    const context = createContext()

    const created = applyDirectAssistantResponse({
      ...context.options,
      responseData: {
        response: '处理完成',
        reasoning_content: '先分析，再回答',
        tools: [{ id: 'tool-1', kind: 'tool', name: '搜索', status: 'completed' }],
        usage: { call_id: 'call-1', provider: 'openai', model: 'gpt-4o-mini' },
      },
    })

    expect(created).toBe(true)
    expect(context.addMessage).toHaveBeenCalledWith('assistant', '处理完成', '先分析，再回答', 'assistant-1')
    expect(context.getMessage().segments).toBeTruthy()
    expect(context.getMessage().toolEvents?.[0]?.id).toBe('tool-1')
    expect(context.getMessageMeta()['assistant-1']?.toolEvents[0]?.id).toBe('tool-1')
    expect(context.dispatchUsageUpdated).toHaveBeenCalledWith({
      callId: 'call-1',
      provider: 'openai',
      model: 'gpt-4o-mini',
    })
  })

  it('writes sanitized backend errors as assistant messages', () => {
    const context = createContext()

    applyDirectAssistantResponse({
      ...context.options,
      responseData: {
        error: { message: '  服务异常  ' },
      },
    })

    expect(context.addMessage).toHaveBeenCalledWith('assistant', '请求失败：服务异常', undefined, 'assistant-1')
    expect(context.getMessage().segments).toBeTruthy()
  })
})