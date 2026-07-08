import { useCallback, useRef, useEffect } from 'react'
import { getAgent, getTranscript } from '@/shared/api/taskRuntimeApi'
import type { AssistantExecutionMeta, AssistantMessageSegment, ToolEventMeta } from '@/features/chat/types'
import {
  syncSubagentSnapshot,
  buildSubagentTranscriptText,
  createEmptyExecutionMeta,
  applySubagentTimeout,
  setSubagentAggregation,
  SUBAGENT_INACTIVITY_TIMEOUT_MS,
} from '@/features/chat/utils/executionMeta'
import { applyToolEventToSegments } from '@/features/chat/utils/assistantSegments'

/** 子代理运行时同步轮询间隔（毫秒） */
const SUBAGENT_RUNTIME_SYNC_INTERVAL_MS = 1200

/** 构建子代理聚合输出行 */
function buildSubagentAggregateLine(name: string, text: string, failed: boolean): string {
  const normalizedText = text.trim()
  if (!normalizedText) {
    return failed ? `[ERROR] Subagent ${name}: 未返回可用输出` : `Subagent ${name}: `
  }
  return failed ? `[ERROR] Subagent ${name}: ${normalizedText}` : `Subagent ${name}: ${normalizedText}`
}

/** 构建子代理续写提示词 */
function buildSubagentContinuationPrompt(): string {
  return '请基于刚刚完成的子代理输出继续完成上一轮任务，并直接给出后续分析或最终答复。'
}

/** handleSend 选项类型，避免循环依赖 */
export interface SendOptions {
  assistantMessageId?: string
  hiddenUserMessage?: boolean
  continuation?: {
    source: string
    aggregated_context: string
    merge_with_last_assistant: boolean
  }
}

export interface UseSubagentSyncParams {
  /** 更新消息执行元数据 */
  updateAssistantMeta: (messageId: string, updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta) => void
  /** 更新消息分段 */
  updateAssistantSegments: (messageId: string, updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[]) => void
  /** 显示提示信息 */
  addToast: (message: string, type: 'success' | 'warning' | 'error' | 'info') => void
  /** 组件挂载状态引用 */
  isMountedRef: React.MutableRefObject<boolean>
  /** 消息元数据引用，用于读取最新元数据 */
  messageMetaRef: React.MutableRefObject<Record<string, AssistantExecutionMeta>>
  /** 发送消息函数引用，用于触发子代理续写 */
  handleSendRef: React.MutableRefObject<((message?: string, attachments?: unknown[], options?: SendOptions) => Promise<void>) | undefined>
}

/**
 * 管理子代理运行时的同步、超时、聚合和续写逻辑。
 *
 * 通过 ref 模式打破循环依赖：
 * - syncSubagentRuntimeRef: 支持递归调度自身
 * - aggregateSubagentOutputsRef: 供 scheduleSubagentAggregation 通过稳定闭包调用
 * - handleSendRef / messageMetaRef: 从 ChatPage 读取最新状态
 */
export function useSubagentSync({
  updateAssistantMeta,
  updateAssistantSegments,
  addToast,
  isMountedRef,
  messageMetaRef,
  handleSendRef,
}: UseSubagentSyncParams) {
  const subagentTimeoutRef = useRef<Record<string, number>>({})
  const subagentSyncTimerRef = useRef<Record<string, number>>({})
  const subagentSyncInFlightRef = useRef<Record<string, boolean>>({})
  const subagentAggregationTimerRef = useRef<Record<string, number>>({})
  const aggregatedSubagentIdsRef = useRef<Record<string, Set<string>>>({})

  // 内部函数 ref，用于稳定闭包之间的相互调用
  const syncSubagentRuntimeRef = useRef<(assistantMessageId: string, agentId: string, agentType?: string) => void>(() => {})
  const aggregateSubagentOutputsRef = useRef<(assistantMessageId: string, subagents: ToolEventMeta[]) => Promise<void>>(async () => {})

  /** 清除指定子代理的超时计时器 */
  const clearSubagentTimeout = useCallback((agentId: string) => {
    const timerId = subagentTimeoutRef.current[agentId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentTimeoutRef.current[agentId]
    }
  }, [])

  /** 清除指定子代理的同步轮询计时器 */
  const clearSubagentSyncTimer = useCallback((agentId: string) => {
    const timerId = subagentSyncTimerRef.current[agentId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentSyncTimerRef.current[agentId]
    }
  }, [])

  /** 清除指定消息的子代理聚合延迟计时器 */
  const clearSubagentAggregationTimer = useCallback((assistantMessageId: string) => {
    const timerId = subagentAggregationTimerRef.current[assistantMessageId]
    if (timerId !== undefined) {
      window.clearTimeout(timerId)
      delete subagentAggregationTimerRef.current[assistantMessageId]
    }
  }, [])

  /** 触发子代理续写，将聚合结果作为上下文发送给主代理 */
  const triggerContinuation = useCallback((assistantMessageId: string, aggregatedText: string) => {
    void handleSendRef.current?.(buildSubagentContinuationPrompt(), undefined, {
      assistantMessageId,
      hiddenUserMessage: true,
      continuation: {
        source: 'subagent',
        aggregated_context: aggregatedText,
        merge_with_last_assistant: true,
      },
    })
  }, [])

  /** 聚合已完成的子代理输出，触发续写 */
  const aggregateSubagentOutputs = useCallback(async (
    assistantMessageId: string,
    subagents: ToolEventMeta[]
  ) => {
    const settledResults = await Promise.allSettled(subagents.map(async (tool) => {
      const fallbackText = tool.subagent?.archivedLogs || tool.subagent?.logs || tool.subagent?.summary || tool.detail || ''
      if (tool.id.startsWith('sub_') || fallbackText.trim()) {
        return buildSubagentAggregateLine(tool.name, fallbackText, tool.status === 'error')
      }

      try {
        const transcriptResponse = await getTranscript(tool.id)
        const transcriptText = buildSubagentTranscriptText(
          Array.isArray(transcriptResponse.transcript) ? transcriptResponse.transcript : []
        )
        const mergedText = transcriptText || fallbackText
        return buildSubagentAggregateLine(tool.name, mergedText, tool.status === 'error')
      } catch {
        const fallbackError = tool.subagent?.errorText || tool.detail || '转录读取失败'
        const fallbackLogs = tool.subagent?.archivedLogs || tool.subagent?.logs || fallbackError
        return buildSubagentAggregateLine(tool.name, fallbackLogs, true)
      }
    }))

    let successCount = 0
    let errorCount = 0
    const lines = settledResults.map((result, index) => {
      const tool = subagents[index]
      const failed = tool.status === 'error' || result.status === 'rejected'
      if (failed) {
        errorCount += 1
      } else {
        successCount += 1
      }

      if (result.status === 'fulfilled') {
        return result.value
      }

      return buildSubagentAggregateLine(tool.name, tool.subagent?.errorText || tool.detail || '转录读取失败', true)
    })

    const mergedText = lines.join('\n\n')
    const aggregatedIds = aggregatedSubagentIdsRef.current[assistantMessageId] || new Set<string>()
    for (const tool of subagents) {
      aggregatedIds.add(tool.id)
    }
    aggregatedSubagentIdsRef.current[assistantMessageId] = aggregatedIds

    updateAssistantMeta(assistantMessageId, (current) => setSubagentAggregation(current, {
      text: current.subagentAggregation?.text
        ? `${current.subagentAggregation.text}\n\n${mergedText}`
        : mergedText,
      total: (current.subagentAggregation?.total || 0) + subagents.length,
      successCount: (current.subagentAggregation?.successCount || 0) + successCount,
      errorCount: (current.subagentAggregation?.errorCount || 0) + errorCount,
      completedAt: Date.now(),
    }))

    if (mergedText.trim()) {
      triggerContinuation(assistantMessageId, mergedText)
    }
  }, [updateAssistantMeta, triggerContinuation])

  // 保持 ref 指向最新的聚合函数，供稳定闭包调用
  // 在 useEffect 中更新 ref，避免在 render 阶段修改 ref 违反 React 纯渲染规则
  useEffect(() => {
    aggregateSubagentOutputsRef.current = aggregateSubagentOutputs
  })

  /** 安排子代理聚合延迟执行，等待所有子代理完成后触发聚合 */
  const scheduleSubagentAggregation = useCallback((assistantMessageId: string) => {
    clearSubagentAggregationTimer(assistantMessageId)
    subagentAggregationTimerRef.current[assistantMessageId] = window.setTimeout(() => {
      const meta = messageMetaRef.current[assistantMessageId]
      const subagents = meta?.toolEvents.filter((tool) => tool.kind === 'subagent') || []
      const aggregatedIds = aggregatedSubagentIdsRef.current[assistantMessageId] || new Set<string>()
      // 前台子代理已在当前 SSE 流中由主代理继续处理，不能再次触发隐藏续写。
      const pendingSubagents = subagents.filter((tool) => (
        tool.subagent?.runMode !== 'foreground' && !aggregatedIds.has(tool.id)
      ))
      const allCompleted = pendingSubagents.length > 0 && pendingSubagents.every((tool) => tool.status === 'completed' || tool.status === 'error')
      if (!allCompleted) {
        return
      }
      void aggregateSubagentOutputsRef.current(assistantMessageId, pendingSubagents)
    }, 80)
  }, [clearSubagentAggregationTimer])

  /** 安排子代理超时检测，超时后标记失败并触发聚合 */
  const scheduleSubagentTimeout = useCallback((assistantMessageId: string, agentId: string, agentType?: string) => {
    clearSubagentTimeout(agentId)
    subagentTimeoutRef.current[agentId] = window.setTimeout(() => {
      const timeoutMessage = `Subagent ${agentType || agentId} 执行失败`
      const timeoutPayload = { agentId, agentType, message: timeoutMessage }

      updateAssistantMeta(assistantMessageId, (current: AssistantExecutionMeta) => applySubagentTimeout(current, timeoutPayload))
      updateAssistantSegments(assistantMessageId, (segments = []) => {
        // 从当前 segments 读取已积累的日志，避免被超时消息覆盖
        const currentTool = (segments || []).flatMap(s => (s && 'toolEvents' in s && Array.isArray(s.toolEvents)) ? s.toolEvents : []).find(t => t && t.id === agentId)
        const tempMeta: AssistantExecutionMeta = { ...createEmptyExecutionMeta(), toolEvents: currentTool ? [currentTool] : [] }
        const toolMeta = applySubagentTimeout(tempMeta, timeoutPayload).toolEvents[0]
        if (!toolMeta) return segments || []
        return applyToolEventToSegments(segments, toolMeta)
      })
      addToast(timeoutMessage, 'error')
      clearSubagentTimeout(agentId)
      scheduleSubagentAggregation(assistantMessageId)
    }, SUBAGENT_INACTIVITY_TIMEOUT_MS)
  }, [addToast, clearSubagentTimeout, updateAssistantMeta, updateAssistantSegments, scheduleSubagentAggregation])

  /** 同步子代理运行时状态，定期轮询直到终态 */
  const syncSubagentRuntime = useCallback((assistantMessageId: string, agentId: string, agentType?: string) => {
    clearSubagentSyncTimer(agentId)
    if (subagentSyncInFlightRef.current[agentId]) {
      return
    }

    subagentSyncInFlightRef.current[agentId] = true
    void (async () => {
      try {
        const [agentResult, transcriptResult] = await Promise.allSettled([
          getAgent(agentId),
          getTranscript(agentId),
        ])

        if (!isMountedRef.current) {
          return
        }

        const agentDetail = agentResult.status === 'fulfilled'
          ? agentResult.value.agent
          : undefined
        const currentTool = messageMetaRef.current[assistantMessageId]?.toolEvents.find((tool) => tool.id === agentId)
        const transcriptText = transcriptResult.status === 'fulfilled'
          ? buildSubagentTranscriptText(
              Array.isArray(transcriptResult.value.transcript) ? transcriptResult.value.transcript : []
            )
          : ''

        const nextAgentType = agentDetail?.agent_type || agentType || currentTool?.subagent?.agentType
        const snapshotPayload = {
          agentId,
          agentType: nextAgentType,
          state: agentDetail?.state,
          logs: transcriptText || currentTool?.subagent?.archivedLogs || currentTool?.subagent?.logs || '',
          summary: typeof agentDetail?.summary === 'string' ? agentDetail.summary : currentTool?.subagent?.summary,
          errorText: typeof agentDetail?.last_error === 'string' ? agentDetail.last_error : currentTool?.subagent?.errorText,
        }

        if (agentDetail || snapshotPayload.logs) {
          updateAssistantMeta(assistantMessageId, (current) => syncSubagentSnapshot(current, snapshotPayload))
          const toolMeta = syncSubagentSnapshot(createEmptyExecutionMeta(), snapshotPayload).toolEvents[0]
          if (toolMeta) {
            updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
          }
        }

        const normalizedState = String(agentDetail?.state || '').trim().toLowerCase()
        const isTerminal = ['completed', 'failed', 'stopped', 'error'].includes(normalizedState)
        if (isTerminal) {
          clearSubagentTimeout(agentId)
          clearSubagentSyncTimer(agentId)
          scheduleSubagentAggregation(assistantMessageId)
          return
        }

        scheduleSubagentTimeout(assistantMessageId, agentId, nextAgentType)
        subagentSyncTimerRef.current[agentId] = window.setTimeout(() => {
          syncSubagentRuntimeRef.current(assistantMessageId, agentId, nextAgentType)
        }, SUBAGENT_RUNTIME_SYNC_INTERVAL_MS)
      } catch {
        if (isMountedRef.current) {
          subagentSyncTimerRef.current[agentId] = window.setTimeout(() => {
            syncSubagentRuntimeRef.current(assistantMessageId, agentId, agentType)
          }, SUBAGENT_RUNTIME_SYNC_INTERVAL_MS)
        }
      } finally {
        delete subagentSyncInFlightRef.current[agentId]
      }
    })()
  }, [clearSubagentSyncTimer, clearSubagentTimeout, updateAssistantMeta, updateAssistantSegments, scheduleSubagentTimeout, scheduleSubagentAggregation, isMountedRef, messageMetaRef])

  // 保持 ref 指向最新的同步函数，支持递归调度
  // 在 useEffect 中更新 ref，避免在 render 阶段修改 ref 违反 React 纯渲染规则
  useEffect(() => {
    syncSubagentRuntimeRef.current = syncSubagentRuntime
  })

  /** 清理所有子代理相关的计时器和状态 */
  const cleanupAllSubagentTimers = useCallback(() => {
    for (const timerId of Object.values(subagentTimeoutRef.current)) {
      window.clearTimeout(timerId)
    }
    subagentTimeoutRef.current = {}
    for (const timerId of Object.values(subagentSyncTimerRef.current)) {
      window.clearTimeout(timerId)
    }
    subagentSyncTimerRef.current = {}
    subagentSyncInFlightRef.current = {}
    for (const timerId of Object.values(subagentAggregationTimerRef.current)) {
      window.clearTimeout(timerId)
    }
    subagentAggregationTimerRef.current = {}
    aggregatedSubagentIdsRef.current = {}
  }, [])

  return {
    clearSubagentTimeout,
    clearSubagentSyncTimer,
    scheduleSubagentTimeout,
    clearSubagentAggregationTimer,
    scheduleSubagentAggregation,
    syncSubagentRuntime,
    cleanupAllSubagentTimers,
  }
}
