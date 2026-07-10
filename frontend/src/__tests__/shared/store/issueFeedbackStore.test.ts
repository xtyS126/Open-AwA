import { describe, it, expect, beforeEach } from 'vitest'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'

describe('issueFeedbackStore', () => {
  beforeEach(() => {
    // 每个测试前重置 store 到初始状态，避免测试间状态污染
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
  })

  it('open 设置 isOpen 为 true 并捕获当前 page_url', () => {
    // 通过 history.pushState 设置当前路径
    window.history.pushState({}, '', '/dashboard?tab=overview')
    useIssueFeedbackStore.getState().open()

    const state = useIssueFeedbackStore.getState()
    expect(state.isOpen).toBe(true)
    // page_url 应为 pathname + search，不含 hash
    expect(state.draft.page_url).toBe('/dashboard?tab=overview')
  })

  it('close 设置 isOpen 为 false 但不清空草稿', () => {
    // 先 open 并填入草稿
    useIssueFeedbackStore.getState().open()
    useIssueFeedbackStore.getState().setDraft({ title: '测试标题', content: '测试内容' })

    useIssueFeedbackStore.getState().close()

    const state = useIssueFeedbackStore.getState()
    expect(state.isOpen).toBe(false)
    // 草稿应保留
    expect(state.draft.title).toBe('测试标题')
    expect(state.draft.content).toBe('测试内容')
  })

  it('setDraft 局部更新草稿字段', () => {
    useIssueFeedbackStore.getState().setDraft({ title: '新标题' })

    const { draft } = useIssueFeedbackStore.getState()
    expect(draft.title).toBe('新标题')
    // 未更新的字段保持默认值
    expect(draft.issue_type).toBe('bug')
    expect(draft.content).toBe('')
  })

  it('setDraft 支持更新 issue_type', () => {
    useIssueFeedbackStore.getState().setDraft({ issue_type: 'suggestion' })

    const { draft } = useIssueFeedbackStore.getState()
    expect(draft.issue_type).toBe('suggestion')
  })

  it('clearDraft 重置草稿到初始空状态', () => {
    useIssueFeedbackStore.getState().setDraft({
      title: '待丢弃',
      content: '内容',
      issue_type: 'question',
    })
    useIssueFeedbackStore.getState().clearDraft()

    const { draft } = useIssueFeedbackStore.getState()
    expect(draft.title).toBe('')
    expect(draft.content).toBe('')
    expect(draft.issue_type).toBe('bug')
    expect(draft.page_url).toBe('')
  })

  it('setSubmitting 切换提交状态', () => {
    useIssueFeedbackStore.getState().setSubmitting(true)
    expect(useIssueFeedbackStore.getState().submitting).toBe(true)

    useIssueFeedbackStore.getState().setSubmitting(false)
    expect(useIssueFeedbackStore.getState().submitting).toBe(false)
  })
})
