/**
 * 派生状态选择器（基于分域 Store）。
 *
 * 使用 Zustand selector 模式，仅当派生值变化时才触发组件重渲染。
 * 每个选择器从对应的分域 Store 读取状态并计算派生值。
 */
import { useModelStore } from '@/features/chat/store/modelStore'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'

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

/**
 * 判断当前选中的模型是否为推理模型（包含 reasoner/r1/o1/o3）。
 * 仅当 selectedModel 变化时触发重渲染。
 */
export function useIsReasonerModel(): boolean {
  return useModelStore((state) => isReasonerModel(state.selectedModel))
}

/**
 * 返回当前会话列表数量。
 * 仅当 conversations 数组引用变化时触发重渲染。
 */
export function useConversationCount(): number {
  return useSessionStore((state) => state.conversations.length)
}

/**
 * 判断是否存在进行中的工具调用。
 * 仅当 activeToolCalls 数组引用变化时触发重渲染。
 */
export function useHasActiveToolCalls(): boolean {
  return useToolCallStore((state) => state.activeToolCalls.length > 0)
}

/**
 * 判断当前会话是否为默认会话（sessionId === 'default'）。
 * 仅当 sessionId 变化时触发重渲染。
 */
export function useIsSessionDefault(): boolean {
  return useSessionStore((state) => state.sessionId === 'default')
}
