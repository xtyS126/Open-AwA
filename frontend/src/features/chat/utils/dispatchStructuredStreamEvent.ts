import type { TodoItem } from '@/features/chat/components/TodoPanel'
import type { AssistantExecutionMeta, AssistantMessageSegment } from '@/features/chat/types'
import {
  applySubagentMessage,
  applySubagentStart,
  applySubagentStop,
  applyTaskUpdate,
  applyToolUpdate,
  buildExecutionMetaFromPayload,
  createEmptyExecutionMeta,
  mergeExecutionMeta,
  normalizeUsage,
  summarizeExecutionResult,
} from '@/features/chat/utils/executionMeta'
import {
  applyIntentToSegments,
  applyStepToSegments,
  applyToolEventToSegments,
  applyToolPatchToSegments,
  applyUsageToSegments,
} from '@/features/chat/utils/assistantSegments'

type StructuredStreamEvent = Record<string, unknown> & { type?: string }

interface DispatchStructuredStreamEventOptions {
  assistantMessageId: string
  messageMeta: Record<string, AssistantExecutionMeta>
  addToast: (message: string, level: 'success' | 'error' | 'warning' | 'info') => void
  updateAssistantMeta: (
    messageId: string,
    updater: (current: AssistantExecutionMeta) => AssistantExecutionMeta,
  ) => void
  updateAssistantSegments: (
    messageId: string,
    updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[],
  ) => void
  clearSubagentAggregationTimer: (assistantMessageId: string) => void
  scheduleSubagentTimeout: (assistantMessageId: string, agentId: string, agentType?: string) => void
  syncSubagentRuntime: (assistantMessageId: string, agentId: string, agentType?: string) => void
  clearSubagentTimeout: (agentId: string) => void
  clearSubagentSyncTimer: (agentId: string) => void
  scheduleSubagentAggregation: (assistantMessageId: string) => void
  setTodoItems: (items: TodoItem[]) => void
  setTodoSummary: (summary: string) => void
  dispatchUsageUpdated: (payload: { callId?: string; provider?: string; model?: string }) => void
  getNow?: () => number
}

function findToolEventInSegments(
  segments: AssistantMessageSegment[] | undefined,
  toolId: string,
) {
  return (segments || [])
    .flatMap((segment) => ('toolEvents' in segment && Array.isArray(segment.toolEvents) ? segment.toolEvents : []))
    .find((tool) => tool.id === toolId)
}

/**
 * 处理流式响应中除 status/chunk 外的结构化事件，避免 ChatPage 在单个回调中承载过多分支。
 */
export function dispatchStructuredStreamEvent(
  event: StructuredStreamEvent,
  options: DispatchStructuredStreamEventOptions,
) {
  const {
    assistantMessageId,
    messageMeta,
    addToast,
    updateAssistantMeta,
    updateAssistantSegments,
    clearSubagentAggregationTimer,
    scheduleSubagentTimeout,
    syncSubagentRuntime,
    clearSubagentTimeout,
    clearSubagentSyncTimer,
    scheduleSubagentAggregation,
    setTodoItems,
    setTodoSummary,
    dispatchUsageUpdated,
    getNow = Date.now,
  } = options

  if (event.type === 'plan' || event.type === 'result') {
    const nextMeta = buildExecutionMetaFromPayload(event)
    updateAssistantMeta(assistantMessageId, (current) => {
      const merged = mergeExecutionMeta(current, nextMeta)
      if (event.type === 'result' && event.result && typeof event.result === 'object') {
        const resultData = event.result as Record<string, unknown>
        const toolId = typeof resultData.tool_id === 'string' ? resultData.tool_id : undefined
        const output = resultData.output !== undefined ? resultData.output : resultData
        if (toolId && output) {
          const toolEvents = merged.toolEvents.map((tool) =>
            tool.id === toolId
              ? {
                  ...tool,
                  output,
                  completedAt: tool.completedAt || getNow(),
                  status: tool.status === 'running' ? 'completed' : tool.status,
                }
              : tool,
          )
          return { ...merged, toolEvents }
        }
      }
      return merged
    })

    if (nextMeta.intent) {
      updateAssistantSegments(assistantMessageId, (segments) => applyIntentToSegments(segments, nextMeta.intent!))
    }

    if (nextMeta.steps.length > 0) {
      updateAssistantSegments(assistantMessageId, (segments = []) => {
        let nextSegments = segments || []
        for (const step of nextMeta.steps) {
          nextSegments = applyStepToSegments(nextSegments, step)
        }
        return nextSegments
      })
    }

    if (event.type === 'result' && event.result && typeof event.result === 'object') {
      const resultData = event.result as Record<string, unknown>
      const toolId = typeof resultData.tool_id === 'string' ? resultData.tool_id : undefined
      const output = resultData.output !== undefined ? resultData.output : resultData
      if (toolId && output !== undefined) {
        updateAssistantSegments(assistantMessageId, (segments) => applyToolPatchToSegments(segments, toolId, {
          output,
          detail: summarizeExecutionResult(output),
          status: 'completed',
          completedAt: getNow(),
        }))
      }
    }
    return
  }

  if (event.type === 'task' && event.task && typeof event.task === 'object') {
    const taskData = event.task as Record<string, unknown>
    updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, taskData))
    const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), taskData).steps[0]
    if (stepMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
    }
    return
  }

  if (event.type === 'tool' && event.tool && typeof event.tool === 'object') {
    const toolData = event.tool as Record<string, unknown>
    const normalizedToolData = {
      ...toolData,
      sequence: toolData.sequence ?? ((messageMeta[assistantMessageId]?.toolEvents.length || 0) + 1),
      input: toolData.input || toolData.arguments || toolData.args,
    }
    updateAssistantMeta(assistantMessageId, (current) => {
      const nextSequence = current.toolEvents.length + 1
      return applyToolUpdate(current, {
        ...normalizedToolData,
        sequence: toolData.sequence ?? nextSequence,
      })
    })
    const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), normalizedToolData).toolEvents[0]
    if (toolMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
    }
    return
  }

  if (event.type === 'subagent_start' && event.agent_id) {
    const agentId = event.agent_id as string
    const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
    const runMode = typeof event.run_mode === 'string' ? event.run_mode : undefined
    const description = typeof event.description === 'string' ? event.description : '子代理已启动'
    const toolMeta = applySubagentStart(createEmptyExecutionMeta(), {
      agentId,
      agentType,
      description,
    }).toolEvents[0]

    updateAssistantMeta(assistantMessageId, (current) => applySubagentStart(current, {
      agentId,
      agentType,
      description,
    }))

    if (toolMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
    }

    clearSubagentAggregationTimer(assistantMessageId)
    scheduleSubagentTimeout(assistantMessageId, agentId, agentType)
    if (!agentId.startsWith('sub_') && runMode !== 'foreground') {
      syncSubagentRuntime(assistantMessageId, agentId, agentType)
    }
    return
  }

  if (event.type === 'subagent_stop' && event.agent_id) {
    const agentId = event.agent_id as string
    const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
    const summary = typeof event.summary === 'string' ? event.summary : `状态: ${event.state}`
    const stopPayload = {
      agentId,
      agentType,
      state: typeof event.state === 'string' ? event.state : undefined,
      summary,
    }

    updateAssistantMeta(assistantMessageId, (current) => applySubagentStop(current, stopPayload))

    let stopStatus: string = 'completed'
    updateAssistantSegments(assistantMessageId, (segments = []) => {
      const currentTool = findToolEventInSegments(segments, agentId)
      const tempMeta: AssistantExecutionMeta = {
        ...createEmptyExecutionMeta(),
        toolEvents: currentTool ? [currentTool] : [],
      }
      const toolMeta = applySubagentStop(tempMeta, stopPayload).toolEvents[0]
      if (!toolMeta) {
        return segments || []
      }
      stopStatus = toolMeta.status === 'error' ? 'error' : 'completed'
      return applyToolEventToSegments(segments, toolMeta)
    })

    if (stopStatus === 'error') {
      addToast(`Subagent ${agentType || agentId} 执行失败`, 'error')
    }

    clearSubagentTimeout(agentId)
    clearSubagentSyncTimer(agentId)
    scheduleSubagentAggregation(assistantMessageId)
    return
  }

  if (event.type === 'agent_message' && event.agent_id) {
    const agentId = event.agent_id as string
    const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
    const messageText = typeof event.message === 'string' ? event.message : '子代理消息'

    updateAssistantMeta(assistantMessageId, (current) => applySubagentMessage(current, {
      agentId,
      agentType,
      message: messageText,
    }))

    updateAssistantSegments(assistantMessageId, (segments = []) => {
      const currentTool = findToolEventInSegments(segments, agentId)
      const tempMeta: AssistantExecutionMeta = {
        ...createEmptyExecutionMeta(),
        toolEvents: currentTool ? [currentTool] : [],
      }
      const toolMeta = applySubagentMessage(tempMeta, {
        agentId,
        agentType,
        message: messageText,
      }).toolEvents[0]
      return applyToolEventToSegments(segments, toolMeta)
    })

    scheduleSubagentTimeout(assistantMessageId, agentId, agentType)
    return
  }

  if (event.type === 'task_created' && event.task) {
    updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, {
      ...event.task,
      status: 'created',
    } as Record<string, unknown>))
    const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), {
      ...(event.task as Record<string, unknown>),
      status: 'created',
    }).steps[0]
    if (stepMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
    }
    return
  }

  if (event.type === 'task_updated' && event.task) {
    const taskData = event.task as Record<string, unknown>
    updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, taskData))
    const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), taskData).steps[0]
    if (stepMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
    }
    return
  }

  if (event.type === 'task_stopped' && event.task_id) {
    const toolPayload = {
      id: event.task_id as string,
      kind: 'task',
      name: '任务已停止',
      status: 'completed',
      detail: typeof event.summary === 'string' ? event.summary : '任务已停止',
    }
    updateAssistantMeta(assistantMessageId, (current) => applyToolUpdate(current, toolPayload))
    const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
    if (toolMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
    }
    return
  }

  if (event.type === 'team_event' && event.team && typeof event.team === 'object') {
    const team = event.team as Record<string, unknown>
    const toolPayload = {
      id: team.team_id || `team_${getNow()}`,
      kind: 'task',
      name: `团队: ${team.name || '未命名'}`,
      status: team.ok === false ? 'failed' : 'running',
      detail: typeof team.state === 'string' ? `团队状态: ${team.state}` : '团队操作已完成',
    }
    updateAssistantMeta(assistantMessageId, (current) => applyToolUpdate(current, toolPayload))
    const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
    if (toolMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
    }
    return
  }

  if (event.type === 'usage' && event.usage) {
    const usage = normalizeUsage(event.usage)
    updateAssistantMeta(assistantMessageId, (current) => ({
      ...current,
      usage: usage || current.usage,
    }))
    if (usage) {
      dispatchUsageUpdated({
        callId: usage.call_id,
        provider: usage.provider,
        model: usage.model,
      })
      updateAssistantSegments(assistantMessageId, (segments) => applyUsageToSegments(segments, usage))
    }
    return
  }

  if (event.type === 'notification') {
    const title = typeof event.title === 'string' ? event.title : ''
    const body = typeof event.body === 'string' ? event.body : ''
    const message = body || title
    if (message) {
      addToast(message, 'info')
    }
    return
  }

  if (event.type === 'todo_update') {
    const todos = Array.isArray(event.todos) ? (event.todos as TodoItem[]) : []
    const summary = typeof event.summary === 'string' ? event.summary : ''
    setTodoItems(todos)
    setTodoSummary(summary)
  }
}