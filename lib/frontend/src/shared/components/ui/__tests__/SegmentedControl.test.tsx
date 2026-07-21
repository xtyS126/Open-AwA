import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SegmentedControl } from '../SegmentedControl'

const options = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
]

describe('SegmentedControl', () => {
  it('渲染所有选项按钮', () => {
    render(<SegmentedControl options={options} value="day" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: '日' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '周' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '月' })).toBeInTheDocument()
  })

  it('当前选中项 aria-pressed 为 true', () => {
    render(<SegmentedControl options={options} value="week" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: '周' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '日' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('点击选项触发 onChange', () => {
    const onChange = vi.fn()
    render(<SegmentedControl options={options} value="day" onChange={onChange} />)
    screen.getByRole('button', { name: '月' }).click()
    expect(onChange).toHaveBeenCalledWith('month')
  })

  it('支持自定义 className', () => {
    const { container } = render(
      <SegmentedControl options={options} value="day" onChange={() => {}} className="my-control" />
    )
    expect(container.firstChild).toHaveClass('my-control')
  })
})
