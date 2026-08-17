/**
 * 偏好相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 outputMode、thinkingEnabled、thinkingDepth 状态管理。
 * 副作用（localStorage 持久化 + 服务端同步）由 chatSyncOrchestrator subscribe 集中处理，
 * setter 只改状态，不直接写 localStorage。
 */
import { create } from 'zustand'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { markSync } from '@/features/chat/store/chatSyncRegistry'
import type { PreferenceMutationOptions } from '@/features/chat/store/chatStoreEffects'
import { isReasonerModel } from '@/features/chat/store/modelStore'

interface PreferenceState {
  /** 输出模式：流式传输或直接输出 */
  outputMode: 'stream' | 'direct'
  /** 是否启用思考模式 */
  thinkingEnabled: boolean
  /** 思考深度（0-5） */
  thinkingDepth: number
  setOutputMode: (mode: 'stream' | 'direct', options?: PreferenceMutationOptions) => void
  setThinkingEnabled: (enabled: boolean, options?: PreferenceMutationOptions) => void
  setThinkingDepth: (depth: number, options?: PreferenceMutationOptions) => void
}

// 初始化时读取本地缓存的选中模型，用于推断思考模式默认值
const initialSelectedModel = safeGetItem('chat_selected_model', '')
const isInitialReasoner = isReasonerModel(initialSelectedModel)

export const usePreferenceStore = create<PreferenceState>((set) => ({
  outputMode: safeGetItem('chat_output_mode', 'stream') as 'stream' | 'direct',
  thinkingEnabled: safeGetItem('chat_thinking_enabled', isInitialReasoner ? 'true' : 'false') === 'true',
  thinkingDepth: Number(safeGetItem('chat_thinking_depth', '0')) || 0,

  setOutputMode: (mode, options) => {
    // 记录同步意图，由 chatSyncOrchestrator subscribe 集中处理持久化
    markSync('outputMode', options?.syncToServer !== false)
    set({ outputMode: mode })
  },

  setThinkingEnabled: (enabled, options) => {
    markSync('thinkingEnabled', options?.syncToServer !== false)
    set({ thinkingEnabled: enabled })
  },

  setThinkingDepth: (depth, options) => {
    // 限制思考深度在 0-5 范围内
    const validDepth = Math.max(0, Math.min(5, depth))
    markSync('thinkingDepth', options?.syncToServer !== false)
    set({ thinkingDepth: validDepth })
  },
}))
