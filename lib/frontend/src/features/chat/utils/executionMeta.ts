import type {
  AssistantExecutionMeta,
  SubagentAggregationMeta,
  SubagentExecutionState,
  TaskStatus,
  TaskStepMeta,
  ToolEventMeta,
  UsageMeta,
} from '@/features/chat/types'
import { asRecord, isRecord } from '@/shared/types/api'

export const SUBAGENT_LOG_LIMIT = 50000
export const SUBAGENT_LOG_TRUNCATE_RATIO = 0.1
export const SUBAGENT_MAX_VISIBLE_CONTAINERS = 20
export const SUBAGENT_INACTIVITY_TIMEOUT_MS = 30000

const SUBAGENT_TRUNCATION_NOTICE = '[日志过长，已截断]\n'
const SUBAGENT_ERROR_PREFIX = /^error\s*[:：]/i

function normalizeSubagentName(agentType: unknown): string {
  const normalizedType = String(agentType || '').trim() || 'unknown'
  return `子代理: ${normalizedType}`
}

function appendSubagentLogs(existingLogs: string, chunk: string): Pick<SubagentExecutionState, 'logs' | 'truncated'> {
  const normalizedChunk = String(chunk || '')
  const baseLogs = String(existingLogs || '')
  const nextRawLogs = baseLogs + normalizedChunk

  const withoutNotice = nextRawLogs.startsWith(SUBAGENT_TRUNCATION_NOTICE)
    ? nextRawLogs.slice(SUBAGENT_TRUNCATION_NOTICE.length)
    : nextRawLogs

  if (withoutNotice.length <= SUBAGENT_LOG_LIMIT) {
    return {
      logs: nextRawLogs,
      truncated: nextRawLogs.startsWith(SUBAGENT_TRUNCATION_NOTICE),
    }
  }

  const truncateOffset = Math.max(1, Math.floor(withoutNotice.length * SUBAGENT_LOG_TRUNCATE_RATIO))
  return {
    logs: `${SUBAGENT_TRUNCATION_NOTICE}${withoutNotice.slice(truncateOffset)}`,
    truncated: true,
  }
}

function getStructuredSubagentLogSeparator(existingLogs: string, _nextChunk: string): string {
  // 已有日志为空或已以换行结尾时无需分隔符
  if (!existingLogs || existingLogs.endsWith('\n')) {
    return ''
  }

  // 每条日志条目都应独占一行，确保 description/message/summary 之间有换行分隔
  return '\n'
}

function normalizeSubagentState(
  incoming: Partial<SubagentExecutionState> | undefined,
  fallbackId: string,
  fallbackStartedAt?: number,
  fallbackCompletedAt?: number,
): SubagentExecutionState | undefined {
  if (!incoming) {
    return undefined
  }

  return {
    agentId: incoming.agentId || fallbackId,
    agentType: incoming.agentType,
    runMode: incoming.runMode,
    logs: String(incoming.logs || ''),
    archivedLogs: typeof incoming.archivedLogs === 'string' ? incoming.archivedLogs : undefined,
    summary: typeof incoming.summary === 'string' ? incoming.summary : undefined,
    errorText: typeof incoming.errorText === 'string' ? incoming.errorText : undefined,
    lastOutputAt: typeof incoming.lastOutputAt === 'number' ? incoming.lastOutputAt : fallbackStartedAt,
    createdAt: typeof incoming.createdAt === 'number' ? incoming.createdAt : fallbackStartedAt,
    completedAt: typeof incoming.completedAt === 'number' ? incoming.completedAt : fallbackCompletedAt,
    exitCode: typeof incoming.exitCode === 'number' ? incoming.exitCode : undefined,
    truncated: Boolean(incoming.truncated),
    timedOut: Boolean(incoming.timedOut),
    visible: incoming.visible !== false,
  }
}

function mergeSubagentState(
  current: SubagentExecutionState | undefined,
  next: SubagentExecutionState | undefined,
  fallbackId: string,
  fallbackStartedAt?: number,
  fallbackCompletedAt?: number,
): SubagentExecutionState | undefined {
  if (!current && !next) {
    return undefined
  }

  return normalizeSubagentState(
    {
      ...current,
      ...next,
      logs: typeof next?.logs === 'string' ? next.logs : current?.logs || '',
      archivedLogs: typeof next?.archivedLogs === 'string' ? next.archivedLogs : current?.archivedLogs,
      visible: next?.visible ?? current?.visible,
    },
    fallbackId,
    fallbackStartedAt,
    fallbackCompletedAt,
  )
}

function compactSubagentContainers(toolEvents: ToolEventMeta[]): ToolEventMeta[] {
  const subagentEvents = toolEvents
    .filter((tool) => tool.kind === 'subagent' && tool.subagent?.visible !== false)
    .filter((tool) => tool.status === 'completed' || tool.status === 'error')
    .sort((left, right) => (left.completedAt || 0) - (right.completedAt || 0))

  const overflow = toolEvents.filter((tool) => tool.kind === 'subagent' && tool.subagent?.visible !== false).length - SUBAGENT_MAX_VISIBLE_CONTAINERS
  if (overflow <= 0 || subagentEvents.length === 0) {
    return toolEvents
  }

  const hiddenIds = new Set(subagentEvents.slice(0, overflow).map((tool) => tool.id))
  return toolEvents.map((tool) => {
    if (!hiddenIds.has(tool.id) || !tool.subagent) {
      return tool
    }

    return {
      ...tool,
      subagent: {
        ...tool.subagent,
        archivedLogs: tool.subagent.archivedLogs || tool.subagent.logs,
        logs: '',
        visible: false,
      },
    }
  })
}

function isSubagentFailure(state: unknown, summary: unknown): boolean {
  // 仅依据后端 subagent_stop 事件的 state 字段判断失败。
  // 不再用正则测试 summary 内容：summary 是子代理的回复文本，
  // 内容不可预测（可能以 "Error:" 开头讨论错误处理），会导致误判。
  // 后端 emit_subagent_stop_event 总是携带权威的 state 字段
  // （completed/failed/error/stopped/timeout），真正失败时 state 会是 'failed'。
  const normalizedState = String(state || '').trim().toLowerCase()
  if (normalizedState === 'failed' || normalizedState === 'error') {
    return true
  }
  // state 为空时，用 summary 作为后备判断（仅匹配纯错误消息格式）
  if (!normalizedState) {
    const normalizedSummary = String(summary || '').trim()
    return SUBAGENT_ERROR_PREFIX.test(normalizedSummary)
  }
  return false
}

function normalizeRuntimeSubagentStatus(state: unknown, hasError: boolean): TaskStatus {
  const normalizedState = String(state || '').trim().toLowerCase()
  if (normalizedState === 'completed' || normalizedState === 'success' || normalizedState === 'done') {
    return 'completed'
  }
  if (hasError || normalizedState === 'failed' || normalizedState === 'error' || normalizedState === 'stopped' || normalizedState === 'timeout') {
    return 'error'
  }
  return 'running'
}

function normalizeSubagentSnapshotLogs(logs: string): Pick<SubagentExecutionState, 'logs' | 'truncated'> {
  const normalizedLogs = String(logs || '')
  if (!normalizedLogs) {
    return {
      logs: '',
      truncated: false,
    }
  }
  return appendSubagentLogs('', normalizedLogs)
}

function transcriptEntryToText(entry: unknown): string {
  if (!entry || typeof entry !== 'object') {
    return String(entry || '').trim()
  }

  const record = asRecord(entry)
  for (const key of ['message', 'content', 'response', 'summary', 'error', 'data']) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }

  return JSON.stringify(record)
}

export function createEmptyExecutionMeta(): AssistantExecutionMeta {
  return {
    steps: [],
    toolEvents: [],
  }
}

export function normalizeTaskStatus(status: unknown): TaskStatus {
  const raw = String(status || '').trim().toLowerCase()
  if (raw === 'completed' || raw === 'success' || raw === 'done') return 'completed'
  if (raw === 'running' || raw === 'processing' || raw === 'in_progress') return 'running'
  if (raw === 'error' || raw === 'failed' || raw === 'failure') return 'error'
  return 'pending'
}

export function summarizeExecutionResult(result: unknown): string {
  if (result && typeof result === 'object') {
    const record = asRecord(result)
    for (const key of ['message', 'response', 'stdout']) {
      const value = record[key]
      if (typeof value === 'string' && value.trim()) {
        return value.trim().slice(0, 160)
      }
    }

    if (typeof record.server_id === 'string' && typeof record.tool_name === 'string' && record.tool_name) {
      return `已完成 ${record.server_id}/${record.tool_name}`
    }

    if (typeof record.status === 'string' && record.status.trim()) {
      return record.status.trim()
    }
  }

  return String(result || '').trim().slice(0, 160)
}

export function applyTaskUpdate(meta: AssistantExecutionMeta, task: Record<string, unknown>): AssistantExecutionMeta {
  const step = Number(task.step || meta.steps.length + 1)
  const action = String(task.action || '')
  const purpose = typeof task.purpose === 'string' ? task.purpose : undefined
  const summary = typeof task.summary === 'string' ? task.summary : undefined
  const status = normalizeTaskStatus(task.status)
  const nextSteps = [...meta.steps]
  const targetIndex = nextSteps.findIndex((item) => item.step === step && item.action === action)
  const nextItem: TaskStepMeta = {
    step,
    action,
    purpose,
    status,
    summary,
  }

  if (targetIndex >= 0) {
    nextSteps[targetIndex] = {
      ...nextSteps[targetIndex],
      ...nextItem,
      purpose: purpose || nextSteps[targetIndex].purpose,
      summary: summary || nextSteps[targetIndex].summary,
    }
  } else {
    nextSteps.push(nextItem)
    nextSteps.sort((left, right) => left.step - right.step)
  }

  return {
    ...meta,
    steps: nextSteps,
  }
}

export function applyToolUpdate(meta: AssistantExecutionMeta, tool: Record<string, unknown>): AssistantExecutionMeta {
  const id = String(tool.id || `${tool.kind || 'tool'}:${tool.name || '未知工具'}`)
  const output = tool.output !== undefined ? tool.output : tool.result
  const normalizedStatus = normalizeTaskStatus(tool.status)
  const rawSubagent = isRecord(tool.subagent)
    ? tool.subagent as Partial<SubagentExecutionState>
    : undefined
  const nextTool: ToolEventMeta = {
    id,
    kind: String(tool.kind || 'tool'),
    name: String(tool.name || '未知工具'),
    status: normalizedStatus,
    detail: typeof tool.detail === 'string' ? tool.detail : summarizeExecutionResult(output),
    input: isRecord(tool.input) ? tool.input : undefined,
    output,
    sequence: typeof tool.sequence === 'number' ? tool.sequence : undefined,
    startedAt: typeof tool.startedAt === 'number' ? tool.startedAt : (normalizedStatus === 'running' ? Date.now() : undefined),
    completedAt: typeof tool.completedAt === 'number' ? tool.completedAt : (normalizedStatus === 'completed' || normalizedStatus === 'error' ? Date.now() : undefined),
    subagent: normalizeSubagentState(rawSubagent, id),
  }
  const nextEvents = [...meta.toolEvents]
  const targetIndex = nextEvents.findIndex((item) => item.id === id)
  if (targetIndex >= 0) {
    nextEvents[targetIndex] = {
      ...nextEvents[targetIndex],
      ...nextTool,
      detail: nextTool.detail || nextEvents[targetIndex].detail,
      input: nextTool.input || nextEvents[targetIndex].input,
      output: nextTool.output !== undefined ? nextTool.output : nextEvents[targetIndex].output,
      sequence: nextTool.sequence ?? nextEvents[targetIndex].sequence,
      startedAt: nextTool.startedAt ?? nextEvents[targetIndex].startedAt,
      completedAt: nextTool.completedAt ?? nextEvents[targetIndex].completedAt,
      subagent: mergeSubagentState(
        nextEvents[targetIndex].subagent,
        nextTool.subagent,
        id,
        nextTool.startedAt ?? nextEvents[targetIndex].startedAt,
        nextTool.completedAt ?? nextEvents[targetIndex].completedAt
      ),
    }
  } else {
    nextEvents.push(nextTool)
  }

  return {
    ...meta,
    toolEvents: compactSubagentContainers(nextEvents),
  }
}

export function applySubagentStart(
  meta: AssistantExecutionMeta,
  payload: { agentId: string; agentType?: string; description?: string; runMode?: 'foreground' | 'background' }
): AssistantExecutionMeta {
  const now = Date.now()
  return applyToolUpdate(meta, {
    id: payload.agentId,
    kind: 'subagent',
    name: normalizeSubagentName(payload.agentType),
    status: 'running',
    detail: payload.description || '子代理已启动',
    startedAt: now,
    subagent: {
      agentId: payload.agentId,
      agentType: payload.agentType,
      runMode: payload.runMode,
      logs: payload.description || '',
      summary: payload.description,
      lastOutputAt: now,
      createdAt: now,
      visible: true,
    },
  })
}

export function applySubagentMessage(
  meta: AssistantExecutionMeta,
  payload: { agentId: string; agentType?: string; message: string }
): AssistantExecutionMeta {
  const existing = meta.toolEvents.find((tool) => tool.id === payload.agentId)
  const nextOutputAt = Date.now()
  const existingLogs = existing?.subagent?.logs || ''
  const logSeparator = getStructuredSubagentLogSeparator(existingLogs, payload.message)
  const nextLogs = appendSubagentLogs(existingLogs, logSeparator + payload.message)

  return applyToolUpdate(meta, {
    id: payload.agentId,
    kind: 'subagent',
    name: normalizeSubagentName(payload.agentType || existing?.subagent?.agentType),
    status: existing?.status === 'error' ? 'error' : 'running',
    detail: payload.message,
    startedAt: existing?.startedAt,
    subagent: {
      agentId: payload.agentId,
      agentType: payload.agentType || existing?.subagent?.agentType,
      logs: nextLogs.logs,
      archivedLogs: existing?.subagent?.archivedLogs,
      lastOutputAt: nextOutputAt,
      createdAt: existing?.subagent?.createdAt || existing?.startedAt || nextOutputAt,
      truncated: nextLogs.truncated,
      visible: existing?.subagent?.visible ?? true,
    },
  })
}

export function applySubagentStop(
  meta: AssistantExecutionMeta,
  payload: { agentId: string; agentType?: string; state?: string; summary?: string; runMode?: 'foreground' | 'background' }
): AssistantExecutionMeta {
  const existing = meta.toolEvents.find((tool) => tool.id === payload.agentId)
  const finishedAt = Date.now()
  const hasError = isSubagentFailure(payload.state, payload.summary)
  const summaryText = String(payload.summary || '').trim()
  const nextLogs = summaryText
    ? appendSubagentLogs(existing?.subagent?.logs || '', (existing?.subagent?.logs && !existing.subagent.logs.endsWith('\n') ? '\n' : '') + summaryText)
    : {
        logs: existing?.subagent?.logs || '',
        truncated: Boolean(existing?.subagent?.truncated),
      }

  return applyToolUpdate(meta, {
    id: payload.agentId,
    kind: 'subagent',
    name: normalizeSubagentName(payload.agentType || existing?.subagent?.agentType),
    status: hasError ? 'error' : 'completed',
    detail: summaryText || (hasError ? '子代理执行失败' : '子代理已完成'),
    startedAt: existing?.startedAt,
    completedAt: finishedAt,
    subagent: {
      agentId: payload.agentId,
      agentType: payload.agentType || existing?.subagent?.agentType,
      runMode: payload.runMode || existing?.subagent?.runMode,
      logs: nextLogs.logs,
      archivedLogs: existing?.subagent?.archivedLogs,
      summary: summaryText || existing?.subagent?.summary,
      errorText: hasError ? (summaryText || existing?.subagent?.errorText || '子代理执行失败') : existing?.subagent?.errorText,
      lastOutputAt: summaryText ? finishedAt : existing?.subagent?.lastOutputAt,
      createdAt: existing?.subagent?.createdAt || existing?.startedAt || finishedAt,
      completedAt: finishedAt,
      exitCode: hasError ? 1 : 0,
      truncated: nextLogs.truncated,
      timedOut: Boolean(existing?.subagent?.timedOut),
      visible: existing?.subagent?.visible ?? true,
    },
  })
}

export function applySubagentTimeout(
  meta: AssistantExecutionMeta,
  payload: { agentId: string; agentType?: string; message?: string }
): AssistantExecutionMeta {
  const existing = meta.toolEvents.find((tool) => tool.id === payload.agentId)
  const timeoutMessage = payload.message || `Subagent ${payload.agentType || payload.agentId} 执行失败`
  const finishedAt = Date.now()
  const nextLogs = appendSubagentLogs(existing?.subagent?.logs || '', (existing?.subagent?.logs && !existing.subagent.logs.endsWith('\n') ? '\n' : '') + `[ERROR] ${timeoutMessage}`)

  return applyToolUpdate(meta, {
    id: payload.agentId,
    kind: 'subagent',
    name: normalizeSubagentName(payload.agentType || existing?.subagent?.agentType),
    status: 'error',
    detail: timeoutMessage,
    startedAt: existing?.startedAt,
    completedAt: finishedAt,
    subagent: {
      agentId: payload.agentId,
      agentType: payload.agentType || existing?.subagent?.agentType,
      logs: nextLogs.logs,
      archivedLogs: existing?.subagent?.archivedLogs,
      summary: timeoutMessage,
      errorText: timeoutMessage,
      lastOutputAt: finishedAt,
      createdAt: existing?.subagent?.createdAt || existing?.startedAt || finishedAt,
      completedAt: finishedAt,
      exitCode: 1,
      truncated: nextLogs.truncated,
      timedOut: true,
      visible: existing?.subagent?.visible ?? true,
    },
  })
}

export function syncSubagentSnapshot(
  meta: AssistantExecutionMeta,
  payload: {
    agentId: string
    agentType?: string
    state?: string
    logs?: string
    summary?: string
    errorText?: string
  }
): AssistantExecutionMeta {
  const existing = meta.toolEvents.find((tool) => tool.id === payload.agentId)
  const summaryText = String(payload.summary || existing?.subagent?.summary || '').trim()
  const errorText = String(payload.errorText || existing?.subagent?.errorText || '').trim()
  const hasError = isSubagentFailure(payload.state, errorText || summaryText)
  const nextStatus = normalizeRuntimeSubagentStatus(payload.state, hasError)
  const nextLogs = normalizeSubagentSnapshotLogs(
    payload.logs || existing?.subagent?.archivedLogs || existing?.subagent?.logs || ''
  )
  const now = Date.now()
  const completedAt = nextStatus === 'running' ? existing?.completedAt : now

  return applyToolUpdate(meta, {
    id: payload.agentId,
    kind: 'subagent',
    name: normalizeSubagentName(payload.agentType || existing?.subagent?.agentType),
    status: nextStatus,
    detail: errorText || summaryText || (nextStatus === 'running' ? '子代理运行中' : '子代理已完成'),
    startedAt: existing?.startedAt,
    completedAt,
    subagent: {
      agentId: payload.agentId,
      agentType: payload.agentType || existing?.subagent?.agentType,
      logs: nextLogs.logs,
      archivedLogs: existing?.subagent?.archivedLogs,
      summary: summaryText || existing?.subagent?.summary,
      errorText: nextStatus === 'error' ? (errorText || summaryText || '子代理执行失败') : undefined,
      lastOutputAt: nextLogs.logs ? now : existing?.subagent?.lastOutputAt,
      createdAt: existing?.subagent?.createdAt || existing?.startedAt || now,
      completedAt,
      exitCode: nextStatus === 'running' ? existing?.subagent?.exitCode : (nextStatus === 'completed' ? 0 : 1),
      truncated: nextLogs.truncated,
      timedOut: Boolean(existing?.subagent?.timedOut),
      visible: existing?.subagent?.visible ?? true,
    },
  })
}

export function getVisibleSubagentTools(toolEvents: ToolEventMeta[]): ToolEventMeta[] {
  return toolEvents.filter((tool) => tool.kind === 'subagent' && tool.subagent?.visible !== false)
}

export function buildSubagentTranscriptText(transcript: unknown[]): string {
  return transcript
    .map((entry) => transcriptEntryToText(entry))
    .filter((line) => line.trim().length > 0)
    .join('\n')
}

export function setSubagentAggregation(
  meta: AssistantExecutionMeta,
  aggregation: SubagentAggregationMeta
): AssistantExecutionMeta {
  return {
    ...meta,
    subagentAggregation: aggregation,
  }
}

export function normalizeUsage(raw: unknown): UsageMeta | undefined {
  if (!raw || typeof raw !== 'object') {
    return undefined
  }

  const usage = asRecord(raw)
  const nextUsage: UsageMeta = {
    call_id: typeof usage.call_id === 'string' ? usage.call_id : undefined,
    provider: typeof usage.provider === 'string' ? usage.provider : undefined,
    model: typeof usage.model === 'string' ? usage.model : undefined,
    input_tokens: Number(usage.input_tokens ?? usage.prompt_tokens ?? 0) || undefined,
    output_tokens: Number(usage.output_tokens ?? usage.completion_tokens ?? 0) || undefined,
    total_cost: Number(usage.total_cost ?? 0) || undefined,
    currency: typeof usage.currency === 'string' ? usage.currency : undefined,
    duration_ms: Number(usage.duration_ms ?? 0) || undefined,
    estimated: Boolean(usage.estimated),
  }

  if (!nextUsage.provider && typeof usage.provider === 'string') {
    nextUsage.provider = usage.provider
  }

  if (!nextUsage.model && typeof usage.model === 'string') {
    nextUsage.model = usage.model
  }

  return nextUsage
}

export function buildExecutionMetaFromPayload(payload: Record<string, unknown>): AssistantExecutionMeta {
  let meta = createEmptyExecutionMeta()

  if (isRecord(payload.plan)) {
    const plan = payload.plan
    meta = {
      ...meta,
      intent: typeof plan.intent === 'string' ? plan.intent : undefined,
      requiresConfirmation: Boolean(plan.requires_confirmation ?? plan.requiresConfirmation),
      steps: Array.isArray(plan.steps)
        ? plan.steps.map((stepRaw: unknown, index: number) => {
            const step = asRecord(stepRaw)
            return {
              step: Number(step.step || index + 1),
              action: String(step.action || ''),
              purpose: typeof step.purpose === 'string' ? step.purpose : undefined,
              status: normalizeTaskStatus(step.status),
              summary: typeof step.summary === 'string' ? step.summary : undefined,
            }
          })
        : [],
    }
  }

  if (Array.isArray(payload.results)) {
    for (const item of payload.results) {
      if (!isRecord(item)) continue
      const result = asRecord(item.result)
      const step = asRecord(item.step)
      meta = applyTaskUpdate(meta, {
        step: step.step ?? result.step,
        action: step.action ?? result.action,
        purpose: step.purpose,
        status: result.status,
        summary: summarizeExecutionResult(result),
      })

      if (item?.type === 'skill') {
        meta = applyToolUpdate(meta, {
          kind: 'skill',
          name: step.skill_name || '技能',
          status: result.status,
          detail: summarizeExecutionResult(result),
        })
      }

      if (item?.type === 'plugin') {
        const pluginName = String(step.plugin_name || '插件')
        const pluginMethod = String(step.plugin_method || '')
        meta = applyToolUpdate(meta, {
          kind: 'plugin',
          name: pluginMethod ? `${pluginName}/${pluginMethod}` : pluginName,
          status: result.status,
          detail: summarizeExecutionResult(result),
        })
      }

      const action = String(result.action || step.action || '')
      if (action === 'mcp_tool_call' || action === 'call_mcp_tool') {
        const serverId = String(result.server_id || '')
        const toolName = String(result.tool_name || '')
        meta = applyToolUpdate(meta, {
          kind: 'mcp',
          name: `${serverId}/${toolName}`.replace(/^\//, ''),
          status: result.status,
          detail: summarizeExecutionResult(result),
        })
      }
    }
  }

  if (Array.isArray(payload.tools)) {
    for (const tool of payload.tools) {
      if (!isRecord(tool)) continue
      meta = applyToolUpdate(meta, tool)
    }
  }

  if (Array.isArray(payload.plugins)) {
    for (const plugin of payload.plugins) {
      if (!isRecord(plugin)) continue
      const pluginName = String(plugin.name || plugin.plugin_name || '插件')
      const toolName = String(plugin.tool || '')
      meta = applyToolUpdate(meta, {
        id: `plugin:${pluginName}/${toolName}`,
        kind: 'plugin',
        name: toolName ? `${pluginName}/${toolName}` : pluginName,
        status: plugin.status,
        detail: typeof plugin.detail === 'string' ? plugin.detail : summarizeExecutionResult(plugin),
      })
    }
  }

  const usage = normalizeUsage(payload.usage)
  if (usage) {
    meta = {
      ...meta,
      usage,
    }
  }

  return meta
}

export function mergeExecutionMeta(base: AssistantExecutionMeta | undefined, incoming: AssistantExecutionMeta): AssistantExecutionMeta {
  let merged = base ? { ...base, steps: [...base.steps], toolEvents: [...base.toolEvents] } : createEmptyExecutionMeta()
  if (incoming.intent) {
    merged.intent = incoming.intent
  }
  if (typeof incoming.requiresConfirmation === 'boolean') {
    merged.requiresConfirmation = incoming.requiresConfirmation
  }
  for (const step of incoming.steps) {
    merged = applyTaskUpdate(merged, asRecord(step))
  }
  for (const toolEvent of incoming.toolEvents) {
    merged = applyToolUpdate(merged, asRecord(toolEvent))
  }
  if (incoming.usage) {
    merged.usage = incoming.usage
  }
  if (incoming.subagentAggregation) {
    merged.subagentAggregation = incoming.subagentAggregation
  }
  return merged
}

export function hasExecutionMeta(meta: AssistantExecutionMeta | undefined): boolean {
  if (!meta) return false
  return Boolean(meta.intent || meta.steps.length || meta.toolEvents.length || meta.usage || meta.subagentAggregation)
}

export function getTaskTitle(step: TaskStepMeta): string {
  if (step.purpose) return step.purpose
  switch (step.action) {
    case 'llm_chat':
      return '生成回复'
    case 'llm_query':
      return '查询信息'
    case 'llm_explain':
      return '解释说明'
    case 'execute_command':
      return '执行命令'
    case 'read_files':
      return '读取文件'
    case 'mcp_tool_call':
    case 'call_mcp_tool':
      return '调用 MCP 工具'
    default:
      return step.action || '执行步骤'
  }
}

export function formatUsageTokens(tokens?: number): string {
  if (!tokens) return '0'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(2)}M`
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`
  return `${tokens}`
}

export function formatUsageCost(amount?: number, currency?: string): string {
  if (!amount) return `${currency === 'CNY' ? '¥' : '$'}0.0000`
  const symbol = currency === 'CNY' ? '¥' : '$'
  if (amount >= 1) return `${symbol}${amount.toFixed(2)}`
  return `${symbol}${amount.toFixed(4)}`
}
