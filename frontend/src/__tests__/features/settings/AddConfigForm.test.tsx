/**
 * AddConfigForm 生图模型开关测试
 * 覆盖：生图开关渲染、用途/限制输入框条件显示、与默认模型互斥
 */
import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import AddConfigForm from '@/features/settings/components/ModelsTab/AddConfigForm'

/** 构造表单 props 的最小集 */
function renderForm(overrides: Record<string, unknown> = {}) {
  const base = {
    show: true,
    newConfig: {
      provider: 'openai',
      model: 'gpt-image-1',
      display_name: '',
      description: '',
      is_default: false,
      is_image_generation: false,
      image_generation_usage: '',
    },
    providers: [],
    providerModels: [],
    adding: false,
    onClose: vi.fn(),
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onFieldChange: vi.fn(),
    onAdd: vi.fn(),
    ...overrides,
  }
  render(<AddConfigForm {...base} />)
  return base
}

describe('AddConfigForm 生图模型开关', () => {
  it('默认不选中生图，不显示用途输入框', () => {
    renderForm()
    const checkbox = screen.getByLabelText(/生图模型/) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    expect(screen.queryByLabelText(/用途与限制/)).toBeNull()
  })

  it('勾选生图开关后显示用途与限制输入框', () => {
    const { onFieldChange } = renderForm()
    const checkbox = screen.getByLabelText(/生图模型/) as HTMLInputElement
    fireEvent.click(checkbox)
    // 受控组件由外部状态驱动，模拟容器回传 is_image_generation=true
    expect(onFieldChange).toHaveBeenCalledWith('is_image_generation', true)

    // 容器状态更新后重新渲染（模拟 ModelsTabContainer 的行为）
    render(
      <AddConfigForm
        show
        newConfig={{ provider: 'openai', model: 'gpt-image-1', display_name: '', description: '', is_default: false, is_image_generation: true, image_generation_usage: '' }}
        providers={[]}
        providerModels={[]}
        adding={false}
        onClose={vi.fn()}
        onProviderChange={vi.fn()}
        onModelChange={vi.fn()}
        onFieldChange={vi.fn()}
        onAdd={vi.fn()}
      />,
    )
    expect(screen.getByPlaceholderText(/写实风格插画/)).toBeInTheDocument()
  })

  it('生图模型与默认模型互斥：勾选生图后默认模型被禁用', () => {
    renderForm({
      newConfig: {
        provider: 'openai',
        model: 'gpt-image-1',
        display_name: '',
        description: '',
        is_default: true,
        is_image_generation: true,
        image_generation_usage: '',
      },
    })
    const defaultCheckbox = screen.getByLabelText(/设为默认模型/) as HTMLInputElement
    expect(defaultCheckbox.disabled).toBe(true)
  })

  it('非生图模型时可正常勾选默认模型', () => {
    renderForm()
    const defaultCheckbox = screen.getByLabelText(/设为默认模型/) as HTMLInputElement
    expect(defaultCheckbox.disabled).toBe(false)
  })
})
