import { describe, expect, it } from 'vitest'
import {
  normalizeSubagentLogText,
  normalizeSubagentTranscriptEntry,
} from '@/features/chat/utils/subagentLogNormalizer'

describe('subagentLogNormalizer', () => {
  it('将运行时 JSON 事件转换为可读摘要且不泄漏原始结构', () => {
    const raw = [
      JSON.stringify({ event: 'subagent_start', description: '检索视频列表' }),
      JSON.stringify({ type: 'plan', plan: { steps: [{ step: 1 }, { step: 2 }] } }),
      JSON.stringify({ type: 'tool', tool: { name: 'builtin_browser_snapshot', status: 'completed', output: { huge: true } } }),
      JSON.stringify({ type: 'chunk', reasoning_content: '先检查接口', content: '## 已找到结果' }),
    ].join('\n')

    const normalized = normalizeSubagentLogText(raw)

    expect(normalized).toContain('[状态] 检索视频列表')
    expect(normalized).toContain('[计划] 已生成 2 个步骤')
    expect(normalized).toContain('[工具] builtin_browser_snapshot: completed')
    expect(normalized).toContain('[思考] 先检查接口')
    expect(normalized).toContain('## 已找到结果')
    expect(normalized).not.toContain('{"type":"plan"')
    expect(normalized).not.toContain('"output"')
  })

  it('忽略无法识别的结构化元数据而不是渲染巨大 JSON', () => {
    const raw = JSON.stringify({ aid: 1, pages: Array.from({ length: 200 }, (_, index) => ({ index })) })
    expect(normalizeSubagentLogText(raw)).toBe('')
  })

  it('从 transcript 条目中只提取真正的消息正文', () => {
    expect(normalizeSubagentTranscriptEntry({
      event: 'agent_message',
      message: JSON.stringify({ type: 'chunk', content: '**最终答案**' }),
    })).toBe('**最终答案**')
  })
})
