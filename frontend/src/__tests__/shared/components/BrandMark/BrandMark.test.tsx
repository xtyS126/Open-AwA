import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BrandMark } from '@/shared/components/BrandMark/BrandMark'

describe('BrandMark', () => {
  it('渲染抽象软晶标记并提供稳定的可访问名称', () => {
    render(<BrandMark />)

    expect(screen.getByRole('img', { name: 'Open-AwA 抽象标记' })).toBeInTheDocument()
    expect(screen.queryByText('A')).not.toBeInTheDocument()
  })

  it('支持无障碍隐藏的装饰性变体', () => {
    const { container } = render(<BrandMark decorative size={24} />)

    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
