import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Badge } from '../Badge'

describe('Badge', () => {
  it('text 模式默认渲染文字标签', () => {
    render(<Badge text="测试中" />)
    const badge = screen.getByText('测试中')
    expect(badge).toBeInTheDocument()
    expect(badge.tagName).toBe('SPAN')
  })

  it('dot 模式渲染圆点元素', () => {
    const { container } = render(<Badge mode="dot" variant="success" />)
    const dot = container.querySelector('span[aria-hidden="true"]')
    expect(dot).toBeInTheDocument()
  })

  it('不同变体渲染对应 class', () => {
    const { rerender, container } = render(<Badge text="警告" variant="warning" />)
    expect(container.firstChild).toHaveClass(/_warning_/)

    rerender(<Badge text="错误" variant="error" />)
    expect(container.firstChild).toHaveClass(/_error_/)
  })

  it('支持自定义 className', () => {
    const { container } = render(<Badge text="自定义" className="my-badge" />)
    expect(container.firstChild).toHaveClass('my-badge')
  })
})
