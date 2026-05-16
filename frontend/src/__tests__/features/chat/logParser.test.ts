import { describe, expect, it } from 'vitest'
import { parseSubagentLogs } from '@/features/chat/utils/logParser'

describe('logParser', () => {
  it('合并连续的思考前缀行为单个思考片段', () => {
    const segments = parseSubagentLogs('[思考] 我\n[思考]正在\n[思考]分析问题')

    expect(segments).toHaveLength(1)
    expect(segments[0]).toMatchObject({
      type: 'think',
      content: '我正在分析问题',
      isClosed: true,
    })
  })

  it('当中间夹杂普通文本时不合并思考片段', () => {
    const segments = parseSubagentLogs('[思考] 先分析\n普通输出\n[思考] 再继续')

    expect(segments.map((segment) => segment.type)).toEqual(['think', 'text', 'think'])
    expect(segments[0].content).toBe('先分析')
    expect(segments[2].content).toBe('再继续')
  })
})