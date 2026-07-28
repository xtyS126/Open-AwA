/**
 * 工具调用相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 activeToolCalls 状态管理，追踪当前进行中的工具调用 ID 列表。
 */
import { create } from 'zustand'

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
