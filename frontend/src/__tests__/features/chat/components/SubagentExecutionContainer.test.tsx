import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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

  it('将被拆开的思考前缀文本渲染为单个思考块', async () => {
    render(
      <SubagentExecutionContainer
        id="agt-think-wrap"
        name="子代理: general-purpose"
        status="completed"
        statusLabel="已完成"
        logs={'从 get_system_status\n[思考] 的结果来看，我们已经有了操作系统信息'}
      />
    )

    fireEvent.click(screen.getByText('思考过程'))

    expect(await screen.findByText('从 get_system_status 的结果来看，我们已经有了操作系统信息')).toBeInTheDocument()
  })

  it('将行内拼接的工具前缀渲染为独立工具卡片', async () => {
    render(
      <SubagentExecutionContainer
        id="agt-inline-tools"
        name="子代理: general-purpose"
        status="running"
        statusLabel="运行中"
        logs={'从 get_system_status[思考] 的结果来看，我们已经有了操作系统信息[工具] builtin_list_files: running[工具] builtin_list_files: 工具调用完成'}
      />
    )

    fireEvent.click(screen.getByText('思考过程'))

    expect(await screen.findByText('从 get_system_status 的结果来看，我们已经有了操作系统信息')).toBeInTheDocument()
    expect(screen.getAllByText('builtin_list_files')).toHaveLength(2)
    expect(screen.getByText('执行中')).toBeInTheDocument()
    expect(screen.getByText('已完成')).toBeInTheDocument()
  })
})