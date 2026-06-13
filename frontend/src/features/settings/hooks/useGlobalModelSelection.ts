/**
 * 全局模型选择 hook，从 chatStore 精确提取设置页需要的字段。
 * 使用 Zustand shallow selector 避免将整个 chatStore（含 IndexedDB 持久化模块）拉入设置页的打包。
 */
import { useChatStore } from '@/features/chat/store/chatStore'

export function useGlobalModelSelection() {
  const selectedModel = useChatStore(s => s.selectedModel)
  const setSelectedModel = useChatStore(s => s.setSelectedModel)
  const modelOptions = useChatStore(s => s.modelOptions)
  const setModelOptions = useChatStore(s => s.setModelOptions)
  const modelLoading = useChatStore(s => s.modelLoading)
  const setModelLoading = useChatStore(s => s.setModelLoading)
  const modelError = useChatStore(s => s.modelError)
  const setModelError = useChatStore(s => s.setModelError)
  const outputMode = useChatStore(s => s.outputMode)
  const setOutputMode = useChatStore(s => s.setOutputMode)

  return {
    selectedModel,
    setSelectedModel,
    modelOptions,
    setModelOptions,
    modelLoading,
    setModelLoading,
    modelError,
    setModelError,
    outputMode,
    setOutputMode,
  }
}
