import { asRecord, isRecord } from '@/shared/types/api'

function getText(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === 'string' ? value.trim() : ''
}

function formatChunk(record: Record<string, unknown>): string {
  const reasoning = getText(record, 'reasoning_content')
  const content = getText(record, 'content')
  if (reasoning && content) return `[思考] ${reasoning}\n${content}`
  if (reasoning) return `[思考] ${reasoning}`
  return content
}

function formatStructuredRecord(record: Record<string, unknown>): string {
  const eventType = getText(record, 'event')
  const chunkType = getText(record, 'type') || getText(record, 'chunk_type')
  const type = eventType || chunkType

  if (type === 'agent_message') {
    return normalizeSubagentLogText(getText(record, 'message'))
  }
  if (type === 'subagent_start') {
    const description = getText(record, 'description')
    return description ? `[状态] ${description}` : '[状态] 子代理已启动'
  }
  if (type === 'subagent_stop') {
    const summary = getText(record, 'summary')
    return summary || '[状态] 子代理已完成'
  }
  if (type === 'chunk') {
    return formatChunk(record)
  }
  if (type === 'status') {
    const message = getText(record, 'message') || getText(record, 'phase')
    return message ? `[状态] ${message}` : ''
  }
  if (type === 'plan') {
    const plan = isRecord(record.plan) ? asRecord(record.plan) : {}
    const steps = Array.isArray(plan.steps) ? plan.steps : []
    return `[计划] 已生成${steps.length > 0 ? ` ${steps.length} 个步骤` : '执行计划'}`
  }
  if (type === 'task') {
    const task = isRecord(record.task) ? asRecord(record.task) : record
    const summary = getText(task, 'summary') || getText(task, 'purpose') || getText(task, 'action')
    const status = getText(task, 'status')
    return summary ? `[任务] ${summary}${status ? ` (${status})` : ''}` : ''
  }
  if (type === 'tool') {
    const tool = isRecord(record.tool) ? asRecord(record.tool) : record
    const name = getText(tool, 'name')
    const detail = getText(tool, 'detail') || getText(tool, 'status')
    return name || detail ? `[工具] ${name}${name && detail ? ': ' : ''}${detail}` : ''
  }
  if (type === 'error') {
    const error = getText(record, 'error') || getText(record, 'message')
    return error ? `[错误] ${error}` : '[错误] 子代理执行失败'
  }

  for (const key of ['message', 'content', 'response', 'summary', 'error', 'data']) {
    const text = getText(record, key)
    if (text) return normalizeSubagentLogText(text)
  }

  // 未识别的运行时元数据不属于用户可读正文，禁止回退成原始 JSON。
  return ''
}

function normalizeLine(line: string): string {
  const trimmed = line.trim()
  if (!trimmed) return ''

  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed: unknown = JSON.parse(trimmed)
      if (isRecord(parsed)) {
        return formatStructuredRecord(asRecord(parsed))
      }
    } catch {
      // 非法 JSON 按普通文本处理，避免误删真实回答。
    }
  }

  return line
}

export function normalizeSubagentLogText(text: string): string {
  return String(text || '')
    .split(/\r?\n/)
    .map(normalizeLine)
    .filter((line) => line.trim().length > 0)
    .join('\n')
}

export function normalizeSubagentTranscriptEntry(entry: unknown): string {
  if (!isRecord(entry)) {
    return normalizeSubagentLogText(String(entry || ''))
  }
  return formatStructuredRecord(asRecord(entry))
}
