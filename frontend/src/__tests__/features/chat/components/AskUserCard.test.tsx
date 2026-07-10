import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { AskUserCard } from '@/features/chat/components/AskUserCard'
import type { AskUserRequest } from '@/features/chat/types'

// mock chatAPI.replyAskUser
vi.mock('@/shared/api/api', () => ({
  chatAPI: {
    replyAskUser: vi.fn(),
  },
}))

import { chatAPI } from '@/shared/api/api'

const mockRequest: AskUserRequest = {
  request_id: 'req-001',
  session_id: 'sess-001',
  question: '你喜欢哪种编程语言？',
  options: ['Python', 'TypeScript', 'Rust'],
  allow_multiple: false,
  allow_free_text: true,
  placeholder: '或输入其他',
  timeout: 300,
}

describe('AskUserCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('request 为 null 时不渲染', () => {
    const { container } = render(<AskUserCard request={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('渲染问题文本和选项', () => {
    render(<AskUserCard request={mockRequest} />)
    expect(screen.getByText('你喜欢哪种编程语言？')).toBeInTheDocument()
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
    expect(screen.getByText('Rust')).toBeInTheDocument()
  })

  it('单选模式点击选项切换选中状态', () => {
    render(<AskUserCard request={mockRequest} />)
    const pythonBtn = screen.getByText('Python').closest('button')!
    const tsBtn = screen.getByText('TypeScript').closest('button')!

    // 点击 Python
    fireEvent.click(pythonBtn)
    expect(pythonBtn).toHaveAttribute('aria-pressed', 'true')
    expect(tsBtn).toHaveAttribute('aria-pressed', 'false')

    // 点击 TypeScript，Python 应取消选中
    fireEvent.click(tsBtn)
    expect(pythonBtn).toHaveAttribute('aria-pressed', 'false')
    expect(tsBtn).toHaveAttribute('aria-pressed', 'true')
  })

  it('多选模式允许多个选项同时选中', () => {
    const multiRequest = { ...mockRequest, allow_multiple: true }
    render(<AskUserCard request={multiRequest} />)

    const pythonBtn = screen.getByText('Python').closest('button')!
    const tsBtn = screen.getByText('TypeScript').closest('button')!

    fireEvent.click(pythonBtn)
    fireEvent.click(tsBtn)

    expect(pythonBtn).toHaveAttribute('aria-pressed', 'true')
    expect(tsBtn).toHaveAttribute('aria-pressed', 'true')
  })

  it('提交回答调用 replyAskUser 并显示成功状态', async () => {
    vi.mocked(chatAPI.replyAskUser).mockResolvedValueOnce({ ok: true, message: 'ok' })
    const onResolved = vi.fn()
    render(<AskUserCard request={mockRequest} onResolved={onResolved} />)

    // 选择选项
    fireEvent.click(screen.getByText('Python'))
    // 输入文本
    fireEvent.change(screen.getByPlaceholderText('或输入其他'), {
      target: { value: '我喜欢它的简洁' },
    })

    // 提交
    const submitBtn = screen.getByText('提交回答').closest('button')!
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(chatAPI.replyAskUser).toHaveBeenCalledWith({
        request_id: 'req-001',
        session_id: 'sess-001',
        answer: '我喜欢它的简洁',
        selected_options: ['Python'],
      })
    })

    await waitFor(() => {
      expect(screen.getByText('已提交')).toBeInTheDocument()
      expect(screen.getByText('回答已提交，等待 AI 继续')).toBeInTheDocument()
    })
    expect(onResolved).toHaveBeenCalled()
  })

  it('提交失败显示错误信息', async () => {
    vi.mocked(chatAPI.replyAskUser).mockRejectedValueOnce(new Error('网络错误'))
    render(<AskUserCard request={mockRequest} />)

    // 输入文本
    fireEvent.change(screen.getByPlaceholderText('或输入其他'), {
      target: { value: '测试回答' },
    })

    const submitBtn = screen.getByText('提交回答').closest('button')!
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByText('网络错误')).toBeInTheDocument()
    })
  })

  it('无选项且文本为空时提交按钮禁用', () => {
    const noOptionsRequest: AskUserRequest = {
      ...mockRequest,
      options: [],
      allow_free_text: true,
    }
    render(<AskUserCard request={noOptionsRequest} />)
    const submitBtn = screen.getByText('提交回答').closest('button')!
    expect(submitBtn).toBeDisabled()
  })

  it('无自由文本且未选选项时提交按钮禁用', () => {
    const noFreeTextRequest: AskUserRequest = {
      ...mockRequest,
      options: ['A', 'B'],
      allow_free_text: false,
    }
    render(<AskUserCard request={noFreeTextRequest} />)
    const submitBtn = screen.getByText('提交回答').closest('button')!
    expect(submitBtn).toBeDisabled()

    // 选择选项后应启用
    fireEvent.click(screen.getByText('A'))
    expect(submitBtn).not.toBeDisabled()
  })
})
