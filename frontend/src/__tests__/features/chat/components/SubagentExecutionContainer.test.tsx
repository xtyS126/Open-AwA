import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SubagentExecutionContainer } from '@/features/chat/components/SubagentExecutionContainer'

describe('SubagentExecutionContainer', () => {
  it('渲染 Markdown 日志和截断提示', async () => {
    const { container } = render(
      <SubagentExecutionContainer
        id="agt-md"
        name="子代理: planner"
        status="running"
        statusLabel="运行中"
        logs={'**粗体测试**'}
        truncated
      />
    )

    expect(screen.getByText('子代理: planner')).toBeInTheDocument()
    expect(screen.getByText('日志过长，已截断')).toBeInTheDocument()
    
    // MessageContent 助手模式使用了 lazy + Suspense，使用 findBy 异步等待渲染完成
    expect(await screen.findByText('粗体测试')).toBeInTheDocument()
    expect(container.querySelector('strong')).not.toBeNull()
  })
})