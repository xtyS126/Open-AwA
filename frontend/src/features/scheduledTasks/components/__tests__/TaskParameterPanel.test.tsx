import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import TaskParameterPanel from '../TaskParameterPanel'

describe('TaskParameterPanel 参数字段同步', () => {
  it('参数结构新增字段后初始化新增字段的默认值', async () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <TaskParameterPanel
        parameters={{
          properties: {
            title: { type: 'string', title: '标题', default: '初始标题' },
          },
        }}
        onChange={onChange}
      />
    )

    expect(screen.getByDisplayValue('初始标题')).toBeInTheDocument()

    rerender(
      <TaskParameterPanel
        parameters={{
          properties: {
            title: { type: 'string', title: '标题', default: '初始标题' },
            count: { type: 'number', title: '次数', default: 3 },
          },
        }}
        onChange={onChange}
      />
    )

    await waitFor(() => {
      expect(screen.getByDisplayValue('3')).toBeInTheDocument()
    })
  })
})
