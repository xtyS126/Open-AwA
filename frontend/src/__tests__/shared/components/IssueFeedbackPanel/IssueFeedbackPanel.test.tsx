import '@testing-library/jest-dom/vitest'
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import IssueFeedbackPanel from '@/shared/components/IssueFeedbackPanel/IssueFeedbackPanel'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'

// mock issueFeedbackAPI，避免真实网络请求
vi.mock('@/shared/api/api', () => ({
  issueFeedbackAPI: {
    submit: vi.fn(),
  },
}))

// 动态导入 mock 后的模块以获取 mock 函数引用
import { issueFeedbackAPI } from '@/shared/api/api'

describe('IssueFeedbackPanel', () => {
  beforeEach(() => {
    // 重置 store 到初始状态
    useIssueFeedbackStore.setState({
      isOpen: false,
      submitting: false,
      draft: {
        issue_type: 'bug',
        title: '',
        content: '',
        page_url: '',
      },
    })
    // 清除 mock 调用记录
    vi.mocked(issueFeedbackAPI.submit).mockReset()
  })

  it('isOpen 为 false 时组件不渲染', () => {
    render(<IssueFeedbackPanel />)

    expect(screen.queryByTestId('issue-feedback-panel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('issue-feedback-overlay')).not.toBeInTheDocument()
  })

  it('isOpen 为 true 时渲染表单字段与提交按钮', () => {
    act(() => {
      useIssueFeedbackStore.getState().open()
    })

    render(<IssueFeedbackPanel />)

    // 类型下拉、标题输入、内容输入、提交按钮都应存在
    expect(screen.getByLabelText('类型')).toBeInTheDocument()
    expect(screen.getByLabelText('标题')).toBeInTheDocument()
    expect(screen.getByLabelText('内容')).toBeInTheDocument()
    // "当前页面"是只读显示，label 未关联表单控件，用 getByText 查询
    expect(screen.getByText('当前页面')).toBeInTheDocument()
    expect(screen.getByTestId('issue-feedback-submit-btn')).toBeInTheDocument()
  })

  it('填写草稿后点击关闭应弹出确认对话框', () => {
    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({ title: '未提交标题' })
    })

    render(<IssueFeedbackPanel />)

    // 点击取消按钮触发关闭
    const cancelBtn = screen.getByText('取消')
    act(() => {
      fireEvent.click(cancelBtn)
    })

    // 确认对话框应出现
    expect(screen.getByTestId('issue-feedback-confirm-dialog')).toBeInTheDocument()
    expect(screen.getByText('是否丢弃未提交的草稿？')).toBeInTheDocument()
  })

  it('提交成功后调用 API、清空草稿并关闭面板', async () => {
    vi.mocked(issueFeedbackAPI.submit).mockResolvedValueOnce({
      ok: true,
      file_id: 'test-file-id',
    })

    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({
        title: '测试标题',
        content: '测试内容',
      })
    })

    render(<IssueFeedbackPanel />)

    const submitBtn = screen.getByTestId('issue-feedback-submit-btn')
    await act(async () => {
      fireEvent.click(submitBtn)
    })

    // API 被调用一次
    expect(issueFeedbackAPI.submit).toHaveBeenCalledTimes(1)
    expect(issueFeedbackAPI.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '测试标题',
        content: '测试内容',
      })
    )

    // 草稿清空 + 面板关闭
    await waitFor(() => {
      expect(useIssueFeedbackStore.getState().isOpen).toBe(false)
      expect(useIssueFeedbackStore.getState().draft.title).toBe('')
      expect(useIssueFeedbackStore.getState().draft.content).toBe('')
    })
  })

  it('提交失败后保留草稿且面板保持打开', async () => {
    vi.mocked(issueFeedbackAPI.submit).mockRejectedValueOnce(new Error('网络错误'))

    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({
        title: '失败的标题',
        content: '失败的内容',
      })
    })

    render(<IssueFeedbackPanel />)

    const submitBtn = screen.getByTestId('issue-feedback-submit-btn')
    await act(async () => {
      fireEvent.click(submitBtn)
    })

    // 草稿保留 + 面板仍开
    expect(useIssueFeedbackStore.getState().isOpen).toBe(true)
    expect(useIssueFeedbackStore.getState().draft.title).toBe('失败的标题')
    expect(useIssueFeedbackStore.getState().draft.content).toBe('失败的内容')
    // submitting 已恢复为 false
    expect(useIssueFeedbackStore.getState().submitting).toBe(false)
  })

  it('标题为空时点击提交不调用 API', async () => {
    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({ content: '只有内容' })
    })

    render(<IssueFeedbackPanel />)

    const submitBtn = screen.getByTestId('issue-feedback-submit-btn')
    await act(async () => {
      fireEvent.click(submitBtn)
    })

    expect(issueFeedbackAPI.submit).not.toHaveBeenCalled()
    expect(useIssueFeedbackStore.getState().isOpen).toBe(true)
  })

  it('点击丢弃按钮清空草稿并关闭面板', () => {
    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({ title: '待丢弃草稿' })
    })

    render(<IssueFeedbackPanel />)

    // 先触发关闭弹出确认对话框
    act(() => {
      fireEvent.click(screen.getByText('取消'))
    })

    // 点击"丢弃"
    act(() => {
      fireEvent.click(screen.getByText('丢弃'))
    })

    expect(useIssueFeedbackStore.getState().isOpen).toBe(false)
    expect(useIssueFeedbackStore.getState().draft.title).toBe('')
    expect(screen.queryByTestId('issue-feedback-confirm-dialog')).not.toBeInTheDocument()
  })

  it('点击保留草稿按钮关闭确认对话框但保留草稿与面板', () => {
    act(() => {
      useIssueFeedbackStore.getState().open()
      useIssueFeedbackStore.getState().setDraft({ title: '保留的草稿' })
    })

    render(<IssueFeedbackPanel />)

    // 触发确认对话框
    act(() => {
      fireEvent.click(screen.getByText('取消'))
    })

    // 点击"保留草稿"
    act(() => {
      fireEvent.click(screen.getByText('保留草稿'))
    })

    // 面板仍开、草稿保留、确认对话框关闭
    expect(useIssueFeedbackStore.getState().isOpen).toBe(true)
    expect(useIssueFeedbackStore.getState().draft.title).toBe('保留的草稿')
    expect(screen.queryByTestId('issue-feedback-confirm-dialog')).not.toBeInTheDocument()
  })
})
