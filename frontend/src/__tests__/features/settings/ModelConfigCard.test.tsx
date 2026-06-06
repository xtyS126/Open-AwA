import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModelParameterEditor, MODEL_PARAM_DEFAULTS, type ModelEditParams } from '@/features/settings/components/ModelParameterEditor'
import { ModelConfigCard } from '@/features/settings/components/ModelConfigCard'

// ==================== ModelParameterEditor ====================

describe('ModelParameterEditor', () => {
  const defaultParams: ModelEditParams = { ...MODEL_PARAM_DEFAULTS, timeout: 120, retry_count: 3 }

  const renderEditor = (overrides?: Partial<ModelEditParams>, disabled = false) => {
    const params = { ...defaultParams, ...overrides }
    const onChange = vi.fn()
    render(<ModelParameterEditor params={params} onChange={onChange} disabled={disabled} />)
    return { onChange, params }
  }

  it('渲染 7 个参数输入区域', () => {
    renderEditor()
    // 温度、Top P、最大 Tokens、频率惩罚、存在惩罚、超时、重试次数
    expect(screen.getByText(/温度 \(Temperature\)/)).toBeInTheDocument()
    expect(screen.getByText(/Top P/)).toBeInTheDocument()
    expect(screen.getByText('最大 Tokens')).toBeInTheDocument()
    expect(screen.getByText(/频率惩罚/)).toBeInTheDocument()
    expect(screen.getByText(/存在惩罚/)).toBeInTheDocument()
    expect(screen.getByText('超时时间（秒）')).toBeInTheDocument()
    // "重试次数" 同时在 label 和 hint 中出现，使用 getAllByText
    expect(screen.getAllByText('重试次数').length).toBeGreaterThanOrEqual(1)
  })

  it('显示温度当前值', () => {
    renderEditor({ temperature: 1.5 })
    expect(screen.getByText(/温度 \(Temperature\): 1\.5/)).toBeInTheDocument()
  })

  it('显示 Top P 当前值（两位小数）', () => {
    renderEditor({ top_p: 0.85 })
    expect(screen.getByText(/Top P: 0\.85/)).toBeInTheDocument()
  })

  it('频率惩罚滑块触发 onChange', () => {
    const { onChange } = renderEditor({ frequency_penalty: 0.5 })
    const sliders = screen.getAllByRole('slider')
    // 第 3 个 slider 是频率惩罚（temperature=0, top_p=1, frequency_penalty=2）
    const freqSlider = sliders[2]
    fireEvent.change(freqSlider, { target: { value: '1.0' } })
    expect(onChange).toHaveBeenCalledWith('frequency_penalty', 1.0)
  })

  it('存在惩罚滑块触发 onChange', () => {
    const { onChange } = renderEditor({ presence_penalty: -0.5 })
    const sliders = screen.getAllByRole('slider')
    // 第 4 个 slider 是存在惩罚
    const presSlider = sliders[3]
    fireEvent.change(presSlider, { target: { value: '0.8' } })
    expect(onChange).toHaveBeenCalledWith('presence_penalty', 0.8)
  })

  it('超时输入清空时恢复默认值 120', () => {
    const { onChange } = renderEditor({ timeout: 300 })
    const timeoutInput = screen.getByPlaceholderText('120')
    fireEvent.change(timeoutInput, { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith('timeout', MODEL_PARAM_DEFAULTS.timeout)
  })

  it('超时输入合法值时触发 onChange', () => {
    const { onChange } = renderEditor()
    const timeoutInput = screen.getByPlaceholderText('120')
    fireEvent.change(timeoutInput, { target: { value: '180' } })
    expect(onChange).toHaveBeenCalledWith('timeout', 180)
  })

  it('重试次数输入清空时恢复默认值 3', () => {
    const { onChange } = renderEditor({ retry_count: 5 })
    const retryInput = screen.getByPlaceholderText('3')
    fireEvent.change(retryInput, { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith('retry_count', MODEL_PARAM_DEFAULTS.retry_count)
  })

  it('最大 Tokens 清空时恢复默认值', () => {
    const { onChange } = renderEditor({ max_tokens: 4096 })
    const maxTokensInput = screen.getByPlaceholderText('默认使用模型上限')
    fireEvent.change(maxTokensInput, { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith('max_tokens', MODEL_PARAM_DEFAULTS.max_tokens)
  })

  it('disabled 模式下所有 slider 不可用', () => {
    renderEditor({}, true)
    const sliders = screen.getAllByRole('slider')
    sliders.forEach(slider => {
      expect(slider).toBeDisabled()
    })
  })

  it('数字输入拒绝超出范围的值', () => {
    const { onChange } = renderEditor({ temperature: 0.5 })
    const numberInputs = screen.getAllByRole('spinbutton')
    // 第一个 spinbutton 是温度
    const tempInput = numberInputs[0]
    fireEvent.change(tempInput, { target: { value: '5.0' } })
    // 5.0 超出 0-2 范围，不应触发 onChange
    expect(onChange).not.toHaveBeenCalledWith('temperature', 5.0)
  })
})

// ==================== ModelConfigCard ====================

describe('ModelConfigCard', () => {
  const defaultParams: ModelEditParams = { ...MODEL_PARAM_DEFAULTS, timeout: 120, retry_count: 3 }

  const renderCard = (overrides?: {
    isExpanded?: boolean
    isSaving?: boolean
    checked?: boolean
    params?: ModelEditParams
    summary?: string
  }) => {
    const onToggle = vi.fn()
    const onSave = vi.fn()
    const onReset = vi.fn()
    const onParamChange = vi.fn()
    const onCheckChange = vi.fn()

    render(
      <ModelConfigCard
        modelName="test-model"
        config={undefined}
        params={overrides?.params ?? defaultParams}
        isExpanded={overrides?.isExpanded ?? false}
        isSaving={overrides?.isSaving ?? false}
        checked={overrides?.checked ?? false}
        summary={overrides?.summary ?? '温度: 0.7'}
        apiEndpoint="https://api.example.com/v1"
        onToggle={onToggle}
        onSave={onSave}
        onReset={onReset}
        onParamChange={onParamChange}
        onCheckChange={onCheckChange}
      />
    )

    return { onToggle, onSave, onReset, onParamChange, onCheckChange }
  }

  it('渲染模型名称', () => {
    renderCard()
    expect(screen.getByText('test-model')).toBeInTheDocument()
  })

  it('折叠状态显示参数摘要', () => {
    renderCard({ summary: '温度: 0.7 · 最大 Tokens: 4K' })
    expect(screen.getByText('温度: 0.7 · 最大 Tokens: 4K')).toBeInTheDocument()
  })

  it('展开状态不显示摘要文本', () => {
    renderCard({ isExpanded: true, summary: '温度: 0.7' })
    expect(screen.queryByText('温度: 0.7')).not.toBeInTheDocument()
  })

  it('展开时显示参数编辑器和操作按钮', () => {
    renderCard({ isExpanded: true })
    expect(screen.getByText('保存参数')).toBeInTheDocument()
    expect(screen.getByText('重置为默认')).toBeInTheDocument()
    expect(screen.getByText(/温度 \(Temperature\)/)).toBeInTheDocument()
  })

  it('折叠时不显示参数编辑器', () => {
    renderCard({ isExpanded: false })
    expect(screen.queryByText('保存参数')).not.toBeInTheDocument()
  })

  it('点击头部触发 onToggle', () => {
    const { onToggle } = renderCard()
    const header = screen.getByRole('button')
    fireEvent.click(header)
    expect(onToggle).toHaveBeenCalledWith('test-model')
  })

  it('键盘 Enter 触发 onToggle', () => {
    const { onToggle } = renderCard()
    const header = screen.getByRole('button')
    fireEvent.keyDown(header, { key: 'Enter' })
    expect(onToggle).toHaveBeenCalledWith('test-model')
  })

  it('保存按钮触发 onSave', () => {
    const { onSave } = renderCard({ isExpanded: true })
    const saveBtn = screen.getByText('保存参数')
    fireEvent.click(saveBtn)
    expect(onSave).toHaveBeenCalledWith('test-model')
  })

  it('保存中状态显示"保存中..."且按钮禁用', () => {
    renderCard({ isExpanded: true, isSaving: true })
    const saveBtn = screen.getByText('保存中...')
    expect(saveBtn).toBeDisabled()
  })

  it('重置按钮触发 onReset', () => {
    const { onReset } = renderCard({ isExpanded: true })
    const resetBtn = screen.getByText('重置为默认')
    fireEvent.click(resetBtn)
    expect(onReset).toHaveBeenCalledWith('test-model')
  })

  it('显示 API 基础地址（只读）', () => {
    renderCard({ isExpanded: true })
    const endpointInput = screen.getByDisplayValue('https://api.example.com/v1')
    expect(endpointInput).toBeDisabled()
  })

  it('复选框变更触发 onCheckChange', () => {
    const { onCheckChange } = renderCard()
    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)
    expect(onCheckChange).toHaveBeenCalledWith('test-model', true)
  })
})
