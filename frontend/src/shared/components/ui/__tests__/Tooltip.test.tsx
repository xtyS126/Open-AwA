import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Tooltip } from '../Tooltip'

describe('Tooltip', () => {
  it('渲染子元素并携带 data-tip 属性', () => {
    render(
      <Tooltip content="提示文字" position="top">
        <button>Hover me</button>
      </Tooltip>
    )
    const btn = screen.getByRole('button', { name: 'Hover me' })
    expect(btn).toBeInTheDocument()
    expect(btn.parentElement).toHaveAttribute('data-tip', '提示文字')
  })

  it('不同方向渲染对应 class', () => {
    const { rerender, container } = render(
      <Tooltip content="上" position="top">
        <span>上</span>
      </Tooltip>
    )
    expect(container.firstChild).toHaveClass(/_top_/)

    rerender(
      <Tooltip content="左" position="left">
        <span>左</span>
      </Tooltip>
    )
    expect(container.firstChild).toHaveClass(/_left_/)
  })

  it('支持自定义 className', () => {
    const { container } = render(
      <Tooltip content="自定义" className="my-tip">
        <span>内容</span>
      </Tooltip>
    )
    expect(container.firstChild).toHaveClass('my-tip')
  })
})
