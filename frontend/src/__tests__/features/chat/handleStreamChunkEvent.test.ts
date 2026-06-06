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

  it('直接追加到可见页面（无 buffer，正常增量流式路径）', () => {
    const ensureAssistantMessage = vi.fn()
    const updateAssistantSegments = vi.fn((_messageId, updater) => updater([]))
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState()

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '增量内容' },
      assistantMessageCreated: true,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: false,
      getNow: () => 4000,
    })

    expect(created).toBe(true)
    expect(updateAssistantSegments).toHaveBeenCalled()
    expect(appendAssistantMessageText).toHaveBeenCalledWith('assistant-1', '增量内容', '')
    expect(flushBuffer).not.toHaveBeenCalled()
  })

  it('隐藏页面缓冲未超时时不触发 flush', () => {
    const ensureAssistantMessage = vi.fn()
    const updateAssistantSegments = vi.fn((_messageId, updater) => updater([]))
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState({ lastUpdateTime: 1000 })

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '新内容' },
      assistantMessageCreated: true,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: true,
      getNow: () => 1500, // 仅过去 500ms，未超 1000ms 阈值
    })

    expect(created).toBe(true)
    expect(buffer.content).toBe('新内容')
    expect(flushBuffer).not.toHaveBeenCalled()
  })

  it('首条消息创建失败时返回 false', () => {
    const ensureAssistantMessage = vi.fn(() => false)
    const updateAssistantSegments = vi.fn()
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState()

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', content: '你好' },
      assistantMessageCreated: false,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: false,
      getNow: () => 9999,
    })

    expect(created).toBe(false)
    expect(updateAssistantSegments).not.toHaveBeenCalled()
  })

  it('处理仅含 reasoning 的 chunk（无正文内容）', () => {
    const ensureAssistantMessage = vi.fn()
    const updateAssistantSegments = vi.fn((_messageId, updater) => updater([]))
    const appendAssistantMessageText = vi.fn()
    const flushBuffer = vi.fn()
    const buffer = createBufferState()

    const created = handleStreamChunkEvent({
      assistantMessageId: 'assistant-1',
      event: { type: 'chunk', reasoning_content: '纯推理内容' },
      assistantMessageCreated: true,
      ensureAssistantMessage,
      updateAssistantSegments,
      appendAssistantMessageText,
      flushBuffer,
      buffer,
      isDocumentHidden: false,
      getNow: () => 5000,
    })

    expect(created).toBe(true)
    expect(updateAssistantSegments).toHaveBeenCalled()
    expect(appendAssistantMessageText).toHaveBeenCalledWith('assistant-1', '', '纯推理内容')
  })
})