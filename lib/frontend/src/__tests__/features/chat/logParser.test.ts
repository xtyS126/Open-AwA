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

  it('将被切开的短前缀文本并回后续思考片段', () => {
    const segments = parseSubagentLogs('从 get_system_status\n[思考] 的结果来看，我们已经有了操作系统信息')

    expect(segments).toHaveLength(1)
    expect(segments[0]).toMatchObject({
      type: 'think',
      content: '从 get_system_status 的结果来看，我们已经有了操作系统信息',
      isClosed: true,
    })
  })

  it('兼容行内拼接的思考与工具前缀', () => {
    const segments = parseSubagentLogs('从 get_system_status[思考] 的结果来看，我们已经有了操作系统信息[工具] builtin_list_files: running[工具] builtin_list_files: 工具调用完成')

    expect(segments.map((segment) => segment.type)).toEqual(['think', 'tool', 'tool'])
    expect(segments[0].content).toBe('从 get_system_status 的结果来看，我们已经有了操作系统信息')
    expect(segments[1]).toMatchObject({
      type: 'tool',
      toolName: 'builtin_list_files',
      toolStatus: 'running',
    })
    expect(segments[2]).toMatchObject({
      type: 'tool',
      toolName: 'builtin_list_files',
      toolStatus: 'completed',
    })
  })

  it('保留已经成句的普通文本与后续思考片段边界', () => {
    const segments = parseSubagentLogs('先输出结论。\n[思考] 再补充原因')

    expect(segments.map((segment) => segment.type)).toEqual(['text', 'think'])
    expect(segments[0].content).toBe('先输出结论。')
    expect(segments[1].content).toBe('再补充原因')
  })
})