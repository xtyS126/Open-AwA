/**
 * 模型相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 selectedModel、modelOptions、modelLoading、modelError 状态管理。
 * 选中推理模型时会跨域调用 preferenceStore 自动开启思考模式。
 */
import { create } from 'zustand'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { persistSelectedModel, type PreferenceMutationOptions } from '@/shared/store/chatStoreEffects'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'

/** 模型配置项，用于全局模型选择 */
export interface ModelOption {
  id: string
  provider: string
  model: string
  display_name: string
}

interface ModelState {
  /** 当前选中的模型标识（格式：provider:model） */
  selectedModel: string
  /** 可选模型列表 */
  modelOptions: ModelOption[]
  /** 模型列表加载状态 */
  modelLoading: boolean
  /** 模型加载错误信息 */
  modelError: string | null
  setSelectedModel: (model: string, options?: PreferenceMutationOptions) => void
  setModelOptions: (options: ModelOption[]) => void
  setModelLoading: (loading: boolean) => void
  setModelError: (error: string | null) => void
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

export const useModelStore = create<ModelState>((set) => ({
  selectedModel: safeGetItem('chat_selected_model', ''),
  modelOptions: [],
  modelLoading: false,
  modelError: null,

  setSelectedModel: (model, options) => {
    set({ selectedModel: model })
    persistSelectedModel(model, options?.syncToServer !== false)
    // 如果选择了推理模型，自动开启思考模式（仅当用户未显式关闭时）
    const isReasoner = isReasonerModel(model)
    if (isReasoner && safeGetItem('chat_thinking_enabled', '') !== 'false') {
      // 跨域调用 preferenceStore 设置思考模式，不同步到服务端（由 thinkingEnabled 自身同步）
      usePreferenceStore.getState().setThinkingEnabled(true, { syncToServer: false })
    }
  },

  setModelOptions: (options) => set({ modelOptions: options }),

  setModelLoading: (loading) => set({ modelLoading: loading }),

  setModelError: (error) => set({ modelError: error }),
}))
