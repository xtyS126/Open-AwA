import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AssistantExecutionMeta, ChatMessage } from '@/features/chat/types'
import { createEmptyExecutionMeta, hasExecutionMeta } from '@/features/chat/utils/executionMeta'

export interface ActiveExecutionState {
  meta: AssistantExecutionMeta
  isStreaming: boolean
}

/**
 * 查找任务面板应展示的最新执行上下文，优先显示当前流式中的 assistant。
 */
export function findLatestActiveExecution(
  messages: ChatMessage[],
  messageMeta: Record<string, AssistantExecutionMeta>,
  streamingAssistantId: string | null
): ActiveExecutionState | null {
  if (streamingAssistantId && messageMeta[streamingAssistantId]) {
    return { meta: messageMeta[streamingAssistantId], isStreaming: true }
  }

  if (streamingAssistantId) {
    return { meta: createEmptyExecutionMeta(), isStreaming: true }
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role === 'assistant' && messageMeta[message.id] && hasExecutionMeta(messageMeta[message.id])) {
      return { meta: messageMeta[message.id], isStreaming: false }
    }
  }

  return null
}

/**
 * 判断任务面板当前是否仍存在进行中的任务或流式过程。
 */
export function hasPendingPanelActivity(activeExecution: ActiveExecutionState | null): boolean {
  if (!activeExecution) {
    return false
  }

  return activeExecution.meta.steps.some((step) => step.status === 'running' || step.status === 'pending') ||
    activeExecution.meta.toolEvents.some((tool) => tool.status === 'running' || tool.status === 'pending') ||
    activeExecution.isStreaming
}

/**
 * 统一管理聊天页任务面板的自动展开、手动切换和当前展示上下文。
 */
export function useTaskPanelState(
  messages: ChatMessage[],
  messageMeta: Record<string, AssistantExecutionMeta>,
  streamingAssistantId: string | null
) {
  const [taskPanelManuallyToggled, setTaskPanelManuallyToggled] = useState(false)
  const [taskPanelExpanded, setTaskPanelExpanded] = useState(false)

  const activeExecution = useMemo(
    () => findLatestActiveExecution(messages, messageMeta, streamingAssistantId),
    [messages, messageMeta, streamingAssistantId]
  )
  const hasActiveTasks = useMemo(() => hasPendingPanelActivity(activeExecution), [activeExecution])

  useEffect(() => {
    if (taskPanelManuallyToggled) {
      return
    }
    setTaskPanelExpanded(hasActiveTasks)
  }, [hasActiveTasks, taskPanelManuallyToggled])

  const toggleTaskPanel = useCallback(() => {
    setTaskPanelManuallyToggled(true)
    setTaskPanelExpanded((current) => !current)
  }, [])

  const resetTaskPanelState = useCallback(() => {
    setTaskPanelManuallyToggled(false)
    setTaskPanelExpanded(false)
  }, [])

  return {
    activeExecution,
    taskPanelExpanded,
    toggleTaskPanel,
    resetTaskPanelState,
  }
}