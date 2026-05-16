import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import { handleStreamChunkEvent, type StreamMessageBufferState } from '@/features/chat/utils/handleStreamChunkEvent'

function createBufferState(overrides?: Partial<StreamMessageBufferState>): StreamMessageBufferState {
  return {
    content: '',
    reasoning: '',
    lastUpdateTime: 1000,
    ...overrides,
  }
}

describe('handleStreamChunkEvent', () => {
  it('creates the first assistant message from the first chunk', () => {
    const ensureAssistantMessage = vi.fn(() => true)
    const updateAssistantSegments = vi.fn()
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState()

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '你好', reasoning_content: '思考中' },
      assistantMessageCreated: false,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: false,
      getNow: () => 2000,
    })

    expect(created).toBe(true)
    expect(ensureAssistantMessage).toHaveBeenCalledWith('你好', '思考中')
    expect(buffer.lastUpdateTime).toBe(2000)
    expect(updateAssistantSegments).not.toHaveBeenCalled()
  })

  it('buffers hidden-page chunks and flushes when idle window is exceeded', () => {
    const ensureAssistantMessage = vi.fn()
    const updateAssistantSegments = vi.fn((messageId, updater) => updater([]))
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState({ lastUpdateTime: 1000 })

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '新内容', reasoning_content: '新推理' },
      assistantMessageCreated: true,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: true,
      getNow: () => 2505,
    })

    expect(created).toBe(true)
    expect(buffer.content).toBe('新内容')
    expect(buffer.reasoning).toBe('新推理')
    expect(updateAssistantSegments).toHaveBeenCalled()
    expect(flushBuffer).toHaveBeenCalledWith('assistant-1')
  })

  it('merges buffered text before flushing on visible pages', () => {
    const ensureAssistantMessage = vi.fn()
    const updateAssistantSegments = vi.fn((messageId, updater) => updater([]))
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState({ content: '旧内容', reasoning: '旧推理' })

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '新内容', reasoning_content: '新推理' },
      assistantMessageCreated: true,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: false,
      getNow: () => 3000,
    })

    expect(created).toBe(true)
    expect(appendAssistantMessageText).toHaveBeenCalledWith('assistant-1', '旧内容新内容', '旧推理新推理')
    expect(buffer.content).toBe('')
    expect(buffer.reasoning).toBe('')
    expect(buffer.lastUpdateTime).toBe(3000)
  })
})