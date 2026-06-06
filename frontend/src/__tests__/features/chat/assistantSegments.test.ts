import { describe, expect, it } from 'vitest'
import {
  appendAssistantChunk,
  applyIntentToSegments,
  applyStepToSegments,
  applyToolEventToSegments,
  applyToolPatchToSegments,
  applyUsageToSegments,
  buildSegmentsFromLegacyMessage,
  finalizeAssistantSegments,
} from '@/features/chat/utils/assistantSegments'

describe('assistantSegments', () => {
  it('将工具调用归入当前思维链，并在正文出现后新建回复段', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '先分析问题。' })
    segments = applyToolEventToSegments(segments, {
      id: 'tool-1',
      kind: 'mcp',
      name: 'filesystem/read_file',
      status: 'completed',
    })
    segments = appendAssistantChunk(segments, { content: '第一轮回复。' })

    expect(segments).toHaveLength(2)
    expect(segments[0]?.kind).toBe('thought')
    expect(segments[1]?.kind).toBe('reply')
    if (segments[0]?.kind === 'thought') {
      expect(segments[0].reasoningContent).toContain('先分析问题')
      expect(segments[0].toolEvents).toHaveLength(1)
    }
    if (segments[1]?.kind === 'reply') {
      expect(segments[1].content).toBe('第一轮回复。')
    }
  })

  it('在已有回复后收到新思考时新开思维链，并合并同一轮正文 chunk', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '思考1' })
    segments = appendAssistantChunk(segments, { content: '回复1' })
    segments = appendAssistantChunk(segments, { reasoningContent: '思考2' })
    segments = applyToolEventToSegments(segments, {
      id: 'tool-2',
      kind: 'task',
      name: '子代理搜索',
      status: 'running',
    })
    segments = appendAssistantChunk(segments, { content: '回复2-A' })
    segments = appendAssistantChunk(segments, { content: '回复2-B' })

    expect(segments.map((segment) => segment.kind)).toEqual(['thought', 'reply', 'thought', 'reply'])
    if (segments[3]?.kind === 'reply') {
      expect(segments[3].content).toBe('回复2-A回复2-B')
    }
  })

  it('没有正文时，如果所有工具已完成且收到新思考，会新开思维链段', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '思考1' })
    segments = applyStepToSegments(segments, {
      step: 1,
      action: 'llm_chat',
      status: 'completed',
      purpose: '分析',
    })
    segments = appendAssistantChunk(segments, { reasoningContent: '思考2' })
    segments = finalizeAssistantSegments(segments)

    expect(segments).toHaveLength(2)
    expect(segments[0]?.kind).toBe('thought')
    expect(segments[1]?.kind).toBe('thought')
    
    if (segments[0]?.kind === 'thought') {
      expect(segments[0].reasoningContent).toContain('思考1')
      expect(segments[0].steps).toHaveLength(1)
      expect(segments[0].status).toBe('completed')
    }
    
    if (segments[1]?.kind === 'thought') {
      expect(segments[1].reasoningContent).toContain('思考2')
      expect(segments[1].steps).toHaveLength(0)
      expect(segments[1].status).toBe('completed')
    }
  })

  it('工具仍在运行中时收到新思考不会新开思维链段', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '思考1' })
    segments = applyStepToSegments(segments, {
      step: 1,
      action: 'llm_chat',
      status: 'running',
      purpose: '分析',
    })
    segments = appendAssistantChunk(segments, { reasoningContent: '思考2' })
    segments = finalizeAssistantSegments(segments)

    expect(segments).toHaveLength(1)
    expect(segments[0]?.kind).toBe('thought')

    if (segments[0]?.kind === 'thought') {
      expect(segments[0].reasoningContent).toContain('思考1')
      expect(segments[0].reasoningContent).toContain('思考2')
      expect(segments[0].steps).toHaveLength(1)
    }
  })

  it('可从旧消息结构派生单轮思维链与回复段', () => {
    const segments = buildSegmentsFromLegacyMessage({
      content: '最终答复',
      reasoningContent: '先思考',
      meta: {
        intent: 'analyse',
        steps: [
          {
            step: 1,
            action: 'llm_chat',
            status: 'completed',
            purpose: '分析问题',
          },
        ],
        toolEvents: [
          {
            id: 'tool-legacy',
            kind: 'mcp',
            name: 'filesystem/read_file',
            status: 'completed',
          },
        ],
        usage: {
          model: 'gpt-4o-mini',
          input_tokens: 10,
          output_tokens: 5,
        },
      },
    })

    expect(segments.map((segment) => segment.kind)).toEqual(['thought', 'reply'])
    if (segments[0]?.kind === 'thought') {
      expect(segments[0].intent).toBe('analyse')
      expect(segments[0].toolEvents).toHaveLength(1)
    }
  })

  it('applyToolPatchToSegments 可修补已有工具事件的输出和状态', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '思考中' })
    segments = applyToolEventToSegments(segments, {
      id: 'tool-patch',
      kind: 'mcp',
      name: 'search',
      status: 'running',
    })
    segments = applyToolPatchToSegments(segments, 'tool-patch', {
      output: '搜索结果',
      status: 'completed',
    })

    if (segments[0]?.kind === 'thought') {
      const tool = segments[0].toolEvents.find((t) => t.id === 'tool-patch')
      expect(tool?.output).toBe('搜索结果')
      expect(tool?.status).toBe('completed')
    }
  })

  it('applyToolPatchToSegments 在空 segments 上不崩溃', () => {
    const result = applyToolPatchToSegments([], 'nonexistent', { output: 'x' })
    expect(result).toEqual([])
  })

  it('applyUsageToSegments 将 usage 信息附加到思维链段', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '思考' })
    segments = applyUsageToSegments(segments, {
      model: 'gpt-4o-mini',
      input_tokens: 100,
      output_tokens: 50,
    })

    expect(segments[0]?.kind).toBe('thought')
    if (segments[0]?.kind === 'thought') {
      expect(segments[0].usage?.model).toBe('gpt-4o-mini')
      expect(segments[0].usage?.input_tokens).toBe(100)
    }
  })

  it('applyIntentToSegments 设置思维链的意图文本', () => {
    let segments = appendAssistantChunk([], { reasoningContent: '分析中' })
    segments = applyIntentToSegments(segments, 'summarize')

    expect(segments[0]?.kind).toBe('thought')
    if (segments[0]?.kind === 'thought') {
      expect(segments[0].intent).toBe('summarize')
    }
  })

  it('processes empty/undefined segments gracefully for core functions', () => {
    expect(() => appendAssistantChunk(undefined, { content: 'test' })).not.toThrow()
    expect(() => finalizeAssistantSegments(undefined)).not.toThrow()
    expect(() => applyUsageToSegments(undefined, { model: 'gpt', input_tokens: 1, output_tokens: 1 })).not.toThrow()
    expect(() => applyIntentToSegments(undefined, 'test')).not.toThrow()

    const chunks = appendAssistantChunk(undefined, { content: 'test' })
    expect(chunks).toHaveLength(1)
    expect(chunks[0]?.kind).toBe('reply')
  })
})
