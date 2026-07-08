/**
 * 偏好相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 outputMode、thinkingEnabled、thinkingDepth 状态管理。
 * 副作用（localStorage 持久化 + 服务端同步）委托给 chatStoreEffects。
 */
import { create } from 'zustand'
import { safeGetItem } from '@/shared/utils/safeStorage'
import {
  persistOutputMode,
  persistThinkingEnabled,
  persistThinkingDepth,
  type PreferenceMutationOptions,
} from '@/features/chat/store/chatStoreEffects'

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

/** 判断指定模型标识是否为推理模型（包含 reasoner/r1/o1/o3） */
function isReasonerModel(model: string): boolean {
  const lower = model.toLowerCase()
  return (
    lower.includes('reasoner') ||
    lower.includes('r1') ||
    lower.includes('o1') ||
    lower.includes('o3')
  )
}

// 初始化时读取本地缓存的选中模型，用于推断思考模式默认值
const initialSelectedModel = safeGetItem('chat_selected_model', '')
const isInitialReasoner = isReasonerModel(initialSelectedModel)

export const usePreferenceStore = create<PreferenceState>((set) => ({
  outputMode: safeGetItem('chat_output_mode', 'stream') as 'stream' | 'direct',
  thinkingEnabled: safeGetItem('chat_thinking_enabled', isInitialReasoner ? 'true' : 'false') === 'true',
  thinkingDepth: Number(safeGetItem('chat_thinking_depth', '0')) || 0,

  setOutputMode: (mode, options) => {
    set({ outputMode: mode })
    persistOutputMode(mode, options?.syncToServer !== false)
  },

  setThinkingEnabled: (enabled, options) => {
    set({ thinkingEnabled: enabled })
    persistThinkingEnabled(enabled, options?.syncToServer !== false)
  },

  setThinkingDepth: (depth, options) => {
    // 限制思考深度在 0-5 范围内
    const validDepth = Math.max(0, Math.min(5, depth))
    set({ thinkingDepth: validDepth })
    persistThinkingDepth(validDepth, options?.syncToServer !== false)
  },
}))
