/**
 * 模型相关状态 Store（分域拆分自 chatStore）。
 *
 * 负责 selectedModel、modelOptions、modelLoading、modelError 状态管理。
 * 选中推理模型时会跨域调用 preferenceStore 自动开启思考模式。
 *
 * selectedModel 的来源优先级：
 *   1. 后端 /user/preferences.selectedModel（由 loadServerPreferences 写入 localStorage）
 *   2. 浏览器 localStorage.chat_selected_model（离线回退）
 *   3. 后端 model_configurations 中 is_default=true 的模型（由 GeneralTabContainer 自动选择）
 *
 * 当后端模型列表变化（如数据库重置）导致 selectedModel 失效时，
 * setModelOptions 会自动清空失效的 selectedModel，触发上层重新选择默认模型。
 */
import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'
import { persistSelectedModel, type PreferenceMutationOptions } from '@/features/chat/store/chatStoreEffects'
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
  resetForLogout: () => void
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

export const useModelStore = create<ModelState>((set, get) => ({
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

  /**
   * 设置模型选项列表，并校验当前 selectedModel 是否仍在新列表中。
   * 场景：数据库重置后 localStorage 仍保留旧模型名（如 deepseek-v4-flash），
   * 但该模型已不在后端 model_configurations 表中。
   * 此时清空 selectedModel 并删除 localStorage，让上层（GeneralTabContainer）自动选择默认模型。
   */
  setModelOptions: (options) => {
    const currentModel = get().selectedModel
    // 仅当本地有选中模型且新选项列表非空时校验
    // 新选项为空表示加载失败或无可用模型，保留旧值避免误清空
    if (currentModel && options.length > 0) {
      const isStillValid = options.some((opt) => opt.id === currentModel)
      if (!isStillValid) {
        // 当前模型已失效：清空 state 和 localStorage，触发上层重新选择默认模型
        set({ modelOptions: options, selectedModel: '' })
        safeSetItem('chat_selected_model', '')
        return
      }
    }
    set({ modelOptions: options })
  },

  setModelLoading: (loading) => set({ modelLoading: loading }),

  setModelError: (error) => set({ modelError: error }),

  resetForLogout: () => {
    safeSetItem('chat_selected_model', '')
    set({ selectedModel: '', modelOptions: [], modelLoading: false, modelError: null })
  },
}))
