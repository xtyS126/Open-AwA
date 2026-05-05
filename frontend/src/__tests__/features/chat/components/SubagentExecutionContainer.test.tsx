import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SubagentExecutionContainer } from '@/features/chat/components/SubagentExecutionContainer'

describe('SubagentExecutionContainer', () => {
  it('渲染 ANSI 日志和截断提示', () => {
    const { container } = render(
      <SubagentExecutionContainer
        id="agt-ansi"
        name="子代理: planner"
        status="running"
        statusLabel="运行中"
        logs={'\u001b[31m错误输出\u001b[0m'}
        truncated
      />
    )

    expect(screen.getByText('子代理: planner')).toBeInTheDocument()
    expect(screen.getByText('日志过长，已截断')).toBeInTheDocument()
    expect(screen.getByText('错误输出')).toBeInTheDocument()
    expect(container.querySelector('pre span')).not.toBeNull()
  })
})