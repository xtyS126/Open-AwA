/**
 * 工具调用相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 activeToolCalls 状态管理，追踪当前进行中的工具调用 ID 列表。
 */
import { create } from 'zustand'
import { registerLogoutHandler } from '@/shared/store/authStore'

interface ToolCallState {
  /** 当前进行中的工具调用 ID 列表 */
  activeToolCalls: string[]
  setActiveToolCalls: (toolIds: string[]) => void
  addActiveToolCall: (toolId: string) => void
  removeActiveToolCall: (toolId: string) => void
  resetActiveToolCalls: () => void
}

export const useToolCallStore = create<ToolCallState>((set) => ({
  activeToolCalls: [],

  setActiveToolCalls: (toolIds) => set({ activeToolCalls: toolIds }),

  addActiveToolCall: (toolId) =>
    set((state) => ({
      activeToolCalls: state.activeToolCalls.includes(toolId)
        ? state.activeToolCalls
        : [...state.activeToolCalls, toolId],
    })),

  removeActiveToolCall: (toolId) =>
    set((state) => ({
      activeToolCalls: state.activeToolCalls.filter((id) => id !== toolId),
    })),

  resetActiveToolCalls: () => set({ activeToolCalls: [] }),
}))

// 登出清理注册：authStore 不再静态导入本 store（避免首屏加载整条 chat 模块链），
// 改由本模块加载时注册登出重置逻辑。
registerLogoutHandler(() => useToolCallStore.getState().resetActiveToolCalls())
