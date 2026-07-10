import type { TodoItem } from '@/features/chat/components/TodoPanel'
import type { AskUserRequest, AssistantExecutionMeta, AssistantMessageSegment, ToolEventMeta } from '@/features/chat/types'
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
import { isRecord } from '@/shared/types/api'

/** 工具函数：安全地将未知值转为 Record 类型（基于类型守卫，无 as 断言） */
function toRecord(value: unknown): Record<string, unknown> | undefined {
  if (isRecord(value)) {
    return value
  }
  return undefined
}

/** 类型守卫：判断事件是否为指定 type */
function isEventType(event: StructuredStreamEvent, type: string): boolean {
  return event.type === type
}

/** 安全获取事件字符串字段 */
function getEventString(event: StructuredStreamEvent, key: string): string | undefined {
  const value = event[key]
  return typeof value === 'string' ? value : undefined
}

/** 安全获取事件未知字段 */
function getEventValue(event: StructuredStreamEvent, key: string): unknown {
  return event[key]
}

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
  /** 收到 ask_user 事件时设置挂起的问题请求（null 表示清空） */
  setAskUserRequest: (request: AskUserRequest | null) => void
  dispatchUsageUpdated: (payload: { callId?: string; provider?: string; model?: string }) => void
  getNow?: () => number
}

function findToolEventInSegments(
  segments: AssistantMessageSegment[] | undefined,
  toolId: string,
): ToolEventMeta | undefined {
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
    setAskUserRequest,
    dispatchUsageUpdated,
    getNow = Date.now,
  } = options

  if (isEventType(event, 'plan') || isEventType(event, 'result')) {
    const nextMeta = buildExecutionMetaFromPayload(event)
    updateAssistantMeta(assistantMessageId, (current) => {
      const merged = mergeExecutionMeta(current, nextMeta)
      if (isEventType(event, 'result')) {
        const resultData = toRecord(getEventValue(event, 'result'))
        if (resultData) {
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

    if (isEventType(event, 'result')) {
      const resultData = toRecord(getEventValue(event, 'result'))
      if (resultData) {
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
    }
    return
  }

  if (isEventType(event, 'task')) {
    const taskData = toRecord(getEventValue(event, 'task'))
    if (taskData) {
      updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, taskData))
      const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), taskData).steps[0]
      if (stepMeta) {
        updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
      }
    }
    return
  }

  if (isEventType(event, 'tool')) {
    const toolData = toRecord(getEventValue(event, 'tool'))
    if (toolData) {
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
    }
    return
  }

  if (isEventType(event, 'subagent_start') && typeof getEventValue(event, 'agent_id') === 'string') {
    const agentId = getEventString(event, 'agent_id')!
    const agentType = getEventString(event, 'agent_type')
    const runMode = getEventString(event, 'run_mode')
    const normalizedRunMode = runMode === 'foreground' || runMode === 'background'
      ? runMode
      : undefined
    const description = getEventString(event, 'description') || '子代理已启动'
    const toolMeta = applySubagentStart(createEmptyExecutionMeta(), {
      agentId,
      agentType,
      description,
      runMode: normalizedRunMode,
    }).toolEvents[0]

    updateAssistantMeta(assistantMessageId, (current) => applySubagentStart(current, {
      agentId,
      agentType,
      description,
      runMode: normalizedRunMode,
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

  if (isEventType(event, 'subagent_stop') && typeof getEventValue(event, 'agent_id') === 'string') {
    const agentId = getEventString(event, 'agent_id')!
    const agentType = getEventString(event, 'agent_type')
    const summary = getEventString(event, 'summary') || `状态: ${getEventValue(event, 'state')}`
    const runMode = getEventString(event, 'run_mode')
    const normalizedRunMode: 'foreground' | 'background' | undefined =
      runMode === 'foreground' || runMode === 'background' ? runMode : undefined
    const stopPayload = {
      agentId,
      agentType,
      state: getEventString(event, 'state'),
      summary,
      runMode: normalizedRunMode,
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

  if (isEventType(event, 'agent_message') && typeof getEventValue(event, 'agent_id') === 'string') {
    const agentId = getEventString(event, 'agent_id')!
    const agentType = getEventString(event, 'agent_type')
    const messageText = getEventString(event, 'message') || '子代理消息'

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

  if (isEventType(event, 'task_created') && getEventValue(event, 'task')) {
    const taskRecord = toRecord(getEventValue(event, 'task'))
    const taskPayload = taskRecord ? { ...taskRecord, status: 'created' } : { status: 'created' }
    updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, taskPayload))
    const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), taskPayload).steps[0]
    if (stepMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
    }
    return
  }

  if (isEventType(event, 'task_updated') && getEventValue(event, 'task')) {
    const taskData = toRecord(getEventValue(event, 'task'))
    if (taskData) {
      updateAssistantMeta(assistantMessageId, (current) => applyTaskUpdate(current, taskData))
      const stepMeta = applyTaskUpdate(createEmptyExecutionMeta(), taskData).steps[0]
      if (stepMeta) {
        updateAssistantSegments(assistantMessageId, (segments) => applyStepToSegments(segments, stepMeta))
      }
    }
    return
  }

  if (isEventType(event, 'task_stopped') && typeof getEventValue(event, 'task_id') === 'string') {
    const toolPayload = {
      id: getEventString(event, 'task_id')!,
      kind: 'task',
      name: '任务已停止',
      status: 'completed',
      detail: getEventString(event, 'summary') || '任务已停止',
    }
    updateAssistantMeta(assistantMessageId, (current) => applyToolUpdate(current, toolPayload))
    const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
    if (toolMeta) {
      updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
    }
    return
  }

  if (isEventType(event, 'team_event')) {
    const team = toRecord(getEventValue(event, 'team'))
    if (team) {
      const toolPayload = {
        id: typeof team.team_id === 'string' ? team.team_id : `team_${getNow()}`,
        kind: 'task',
        name: `团队: ${typeof team.name === 'string' ? team.name : '未命名'}`,
        status: team.ok === false ? 'failed' : 'running',
        detail: typeof team.state === 'string' ? `团队状态: ${team.state}` : '团队操作已完成',
      }
      updateAssistantMeta(assistantMessageId, (current) => applyToolUpdate(current, toolPayload))
      const toolMeta = applyToolUpdate(createEmptyExecutionMeta(), toolPayload).toolEvents[0]
      if (toolMeta) {
        updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
      }
    }
    return
  }

  if (isEventType(event, 'usage') && getEventValue(event, 'usage')) {
    const usage = normalizeUsage(getEventValue(event, 'usage'))
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

  if (isEventType(event, 'notification')) {
    const title = getEventString(event, 'title') || ''
    const body = getEventString(event, 'body') || ''
    const message = body || title
    if (message) {
      addToast(message, 'info')
    }
    return
  }

  if (isEventType(event, 'todo_update')) {
    const todosValue = getEventValue(event, 'todos')
    const todos = Array.isArray(todosValue) ? (todosValue as TodoItem[]) : []
    const summary = getEventString(event, 'summary') || ''
    setTodoItems(todos)
    setTodoSummary(summary)
  }

  if (isEventType(event, 'ask_user')) {
    // ask_user 事件：AI 主动向用户提问，渲染问题卡片等待回答
    const payload = toRecord(getEventValue(event, 'ask_user'))
    if (payload === undefined) {
      return
    }
    const requestId = typeof payload.request_id === 'string' ? payload.request_id : ''
    const sessionId = typeof payload.session_id === 'string' ? payload.session_id : ''
    const question = typeof payload.question === 'string' ? payload.question : ''
    if (!requestId || !question) {
      return
    }
    const optionsRaw = payload.options
    const optionsList = Array.isArray(optionsRaw)
      ? optionsRaw.filter((o): o is string => typeof o === 'string')
      : []
    const askUserRequest: AskUserRequest = {
      request_id: requestId,
      session_id: sessionId,
      question,
      options: optionsList,
      allow_multiple: payload.allow_multiple === true,
      allow_free_text: payload.allow_free_text !== false,
      placeholder: typeof payload.placeholder === 'string' ? payload.placeholder : '',
      timeout: typeof payload.timeout === 'number' ? payload.timeout : 300,
      created_at: typeof payload.created_at === 'number' ? payload.created_at : undefined,
    }
    setAskUserRequest(askUserRequest)
  }
}
