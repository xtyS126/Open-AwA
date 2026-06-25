/**
 * 全局模型选择 hook，从分域 Store 精确提取设置页需要的字段。
 * 使用 Zustand selector 避免将整个 Store 拉入设置页的打包。
 *
 * 模型相关状态来自 modelStore，输出模式来自 preferenceStore。
 */
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'

export function useGlobalModelSelection() {
  const selectedModel = useModelStore(s => s.selectedModel)
  const setSelectedModel = useModelStore(s => s.setSelectedModel)
  const modelOptions = useModelStore(s => s.modelOptions)
  const setModelOptions = useModelStore(s => s.setModelOptions)
  const modelLoading = useModelStore(s => s.modelLoading)
  const setModelLoading = useModelStore(s => s.setModelLoading)
  const modelError = useModelStore(s => s.modelError)
  const setModelError = useModelStore(s => s.setModelError)
  const outputMode = usePreferenceStore(s => s.outputMode)
  const setOutputMode = usePreferenceStore(s => s.setOutputMode)

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
