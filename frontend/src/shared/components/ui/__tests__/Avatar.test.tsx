import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Avatar } from '../Avatar'

describe('Avatar', () => {
  it('有 src 时渲染 img 元素', () => {
    render(<Avatar src="https://example.com/a.png" alt="头像" />)
    const img = screen.getByRole('img')
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('src', 'https://example.com/a.png')
  })

  it('无 src 时渲染文字回退', () => {
    render(<Avatar alt="张三" />)
    const fallback = screen.getByText('张')
    expect(fallback).toBeInTheDocument()
    expect(fallback).toHaveClass(/_fallback_/)
  })

  it('不同尺寸渲染对应 class', () => {
    const { rerender, container } = render(<Avatar alt="A" size="sm" />)
    expect(container.firstChild).toHaveClass(/_sm_/)

    rerender(<Avatar alt="A" size="lg" />)
    expect(container.firstChild).toHaveClass(/_lg_/)
  })

  it('不同形状渲染对应 class', () => {
    const { rerender, container } = render(<Avatar alt="A" shape="circle" />)
    expect(container.firstChild).toHaveClass(/_circle_/)

    rerender(<Avatar alt="A" shape="rounded" />)
    expect(container.firstChild).toHaveClass(/_rounded_/)
  })

  it('支持自定义 className', () => {
    const { container } = render(<Avatar alt="A" className="my-avatar" />)
    expect(container.firstChild).toHaveClass('my-avatar')
  })
})
