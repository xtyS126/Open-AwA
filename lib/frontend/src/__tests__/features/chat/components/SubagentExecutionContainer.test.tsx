import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SubagentExecutionContainer } from '@/features/chat/components/SubagentExecutionContainer'

describe('SubagentExecutionContainer', () => {
  it('渲染容器、标题、状态和截断提示', () => {
    render(
      <SubagentExecutionContainer
        id="agt-md"
        name="子代理: planner"
        status="running"
        statusLabel="运行中"
        logs="**粗体测试**"
        truncated
      />
    )

    expect(screen.getByText('子代理: planner')).toBeInTheDocument()
    expect(screen.getByText('运行中')).toBeInTheDocument()
    expect(screen.getByText('日志过长，已截断')).toBeInTheDocument()
    // logs 内容由 ParsedSubagentLogs + lazy MessageContent 渲染，验证容器存在即可
    expect(screen.getByTestId('subagent-container-agt-md')).toBeInTheDocument()
  })

  it('默认状态标签正确映射', () => {
    render(
      <SubagentExecutionContainer
        id="agt-defaults"
        name="子代理: test"
        status="completed"
        logs="done"
      />
    )

    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.queryByText('日志过长，已截断')).not.toBeInTheDocument()
  })

  it('错误状态显示异常标签', () => {
    render(
      <SubagentExecutionContainer
        id="agt-err"
        name="子代理: test"
        status="error"
        logs="error"
      />
    )

    expect(screen.getByText('异常')).toBeInTheDocument()
  })
})
