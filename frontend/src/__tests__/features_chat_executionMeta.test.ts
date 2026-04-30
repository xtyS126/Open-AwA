import { describe, expect, it } from 'vitest'
import { applyToolUpdate, createEmptyExecutionMeta, normalizeTaskStatus } from '@/features/chat/utils/executionMeta'

describe('executionMeta', () => {
  it('将 done 识别为已完成状态', () => {
    expect(normalizeTaskStatus('done')).toBe('completed')
  })

  it('兼容 result 字段并自动提取工具摘要', () => {
    const meta = applyToolUpdate(createEmptyExecutionMeta(), {
      id: 'tool-1',
      kind: 'plugin',
      name: 'hello-world/say_hello',
      status: 'done',
      result: {
        message: 'Hello, Open-AwA!',
      },
    })

    expect(meta.toolEvents).toHaveLength(1)
    expect(meta.toolEvents[0].status).toBe('completed')
    expect(meta.toolEvents[0].detail).toBe('Hello, Open-AwA!')
    expect(meta.toolEvents[0].output).toEqual({
      message: 'Hello, Open-AwA!',
    })
  })
})
