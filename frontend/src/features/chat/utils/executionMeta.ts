import type { AssistantExecutionMeta, TaskStatus, TaskStepMeta, ToolEventMeta, UsageMeta } from '@/features/chat/types'

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
    const record = result as Record<string, unknown>
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
  const nextTool: ToolEventMeta = {
    id,
    kind: String(tool.kind || 'tool'),
    name: String(tool.name || '未知工具'),
    status: normalizeTaskStatus(tool.status),
    detail: typeof tool.detail === 'string' ? tool.detail : summarizeExecutionResult(output),
    input: tool.input && typeof tool.input === 'object' ? (tool.input as Record<string, unknown>) : undefined,
    output,
    sequence: typeof tool.sequence === 'number' ? tool.sequence : undefined,
    startedAt: typeof tool.startedAt === 'number' ? tool.startedAt : (tool.status === 'running' ? Date.now() : undefined),
    completedAt: typeof tool.completedAt === 'number' ? tool.completedAt : (tool.status === 'completed' || tool.status === 'error' ? Date.now() : undefined),
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
    }
  } else {
    nextEvents.push(nextTool)
  }

  return {
    ...meta,
    toolEvents: nextEvents,
  }
}

export function normalizeUsage(raw: unknown): UsageMeta | undefined {
  if (!raw || typeof raw !== 'object') {
    return undefined
  }

  const usage = raw as Record<string, unknown>
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

export function buildExecutionMetaFromPayload(payload: Record<string, any>): AssistantExecutionMeta {
  let meta = createEmptyExecutionMeta()

  if (payload.plan && typeof payload.plan === 'object') {
    meta = {
      ...meta,
      intent: typeof payload.plan.intent === 'string' ? payload.plan.intent : undefined,
      requiresConfirmation: Boolean(payload.plan.requires_confirmation ?? payload.plan.requiresConfirmation),
      steps: Array.isArray(payload.plan.steps)
        ? payload.plan.steps.map((step: Record<string, unknown>, index: number) => ({
            step: Number(step.step || index + 1),
            action: String(step.action || ''),
            purpose: typeof step.purpose === 'string' ? step.purpose : undefined,
            status: normalizeTaskStatus(step.status),
            summary: typeof step.summary === 'string' ? step.summary : undefined,
          }))
        : [],
    }
  }

  if (Array.isArray(payload.results)) {
    for (const item of payload.results) {
      const result = item && typeof item.result === 'object' ? item.result : {}
      const step = item && typeof item.step === 'object' ? item.step : {}
      meta = applyTaskUpdate(meta, {
        step: (step as Record<string, unknown>).step ?? (result as Record<string, unknown>).step,
        action: (step as Record<string, unknown>).action ?? (result as Record<string, unknown>).action,
        purpose: (step as Record<string, unknown>).purpose,
        status: (result as Record<string, unknown>).status,
        summary: summarizeExecutionResult(result),
      })

      if (item?.type === 'skill') {
        meta = applyToolUpdate(meta, {
          kind: 'skill',
          name: (step as Record<string, unknown>).skill_name || '技能',
          status: (result as Record<string, unknown>).status,
          detail: summarizeExecutionResult(result),
        })
      }

      if (item?.type === 'plugin') {
        const pluginName = String((step as Record<string, unknown>).plugin_name || '插件')
        const pluginMethod = String((step as Record<string, unknown>).plugin_method || '')
        meta = applyToolUpdate(meta, {
          kind: 'plugin',
          name: pluginMethod ? `${pluginName}/${pluginMethod}` : pluginName,
          status: (result as Record<string, unknown>).status,
          detail: summarizeExecutionResult(result),
        })
      }

      const action = String((result as Record<string, unknown>).action || (step as Record<string, unknown>).action || '')
      if (action === 'mcp_tool_call' || action === 'call_mcp_tool') {
        const serverId = String((result as Record<string, unknown>).server_id || '')
        const toolName = String((result as Record<string, unknown>).tool_name || '')
        meta = applyToolUpdate(meta, {
          kind: 'mcp',
          name: `${serverId}/${toolName}`.replace(/^\//, ''),
          status: (result as Record<string, unknown>).status,
          detail: summarizeExecutionResult(result),
        })
      }
    }
  }

  if (Array.isArray(payload.tools)) {
    for (const tool of payload.tools) {
      if (!tool || typeof tool !== 'object') continue
      meta = applyToolUpdate(meta, tool as Record<string, unknown>)
    }
  }

  if (Array.isArray(payload.plugins)) {
    for (const plugin of payload.plugins) {
      if (!plugin || typeof plugin !== 'object') continue
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
    merged = applyTaskUpdate(merged, step as unknown as Record<string, unknown>)
  }
  for (const toolEvent of incoming.toolEvents) {
    merged = applyToolUpdate(merged, toolEvent as unknown as Record<string, unknown>)
  }
  if (incoming.usage) {
    merged.usage = incoming.usage
  }
  return merged
}

export function hasExecutionMeta(meta: AssistantExecutionMeta | undefined): boolean {
  if (!meta) return false
  return Boolean(meta.intent || meta.steps.length || meta.toolEvents.length || meta.usage)
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
