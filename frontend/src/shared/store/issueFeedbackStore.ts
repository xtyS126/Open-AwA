/**
 * 问题反馈浮动面板的全局状态。
 * 跨路由持久（挂在 AppShell 顶层，不在 Outlet 内部），路由切换不卸载。
 * 草稿在组件卸载后仍保留在 store 中，重新打开时恢复。
 */
import { create } from 'zustand'
import type { IssueFeedbackType } from '@/shared/api/types'

/** 反馈草稿结构 */
interface IssueFeedbackDraft {
  issue_type: IssueFeedbackType
  title: string
  content: string
  page_url: string
}

interface IssueFeedbackState {
  /** 面板是否展开 */
  isOpen: boolean
  /** 提交中状态（禁用按钮、防止重复提交） */
  submitting: boolean
  /** 草稿内容，跨打开/关闭保留 */
  draft: IssueFeedbackDraft
  /** 打开面板，自动捕获当前页面 URL（pathname + search，不含 hash） */
  open: () => void
  /** 关闭面板（不清空草稿） */
  close: () => void
  /** 局部更新草稿字段 */
  setDraft: (patch: Partial<IssueFeedbackDraft>) => void
  /** 清空草稿到初始状态 */
  clearDraft: () => void
  /** 设置提交中状态 */
  setSubmitting: (v: boolean) => void
}

/** 初始空草稿常量，clearDraft 与初始状态共用 */
const EMPTY_DRAFT: IssueFeedbackDraft = {
  issue_type: 'bug',
  title: '',
  content: '',
  page_url: '',
}

export const useIssueFeedbackStore = create<IssueFeedbackState>((set) => ({
  isOpen: false,
  submitting: false,
  draft: { ...EMPTY_DRAFT },
  open: () =>
    set((state) => ({
      isOpen: true,
      draft: {
        ...state.draft,
        // 打开时自动捕获当前页面 URL（截取 pathname + search，不含 hash）
        page_url: window.location.pathname + window.location.search,
      },
    })),
  close: () => set({ isOpen: false }),
  setDraft: (patch) =>
    set((state) => ({ draft: { ...state.draft, ...patch } })),
  clearDraft: () => set({ draft: { ...EMPTY_DRAFT } }),
  setSubmitting: (v) => set({ submitting: v }),
}))
