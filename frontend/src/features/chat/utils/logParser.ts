export type LogSegmentType = 'text' | 'think' | 'terminal' | 'tool' | 'task' | 'status' | 'plan' | 'error'

export interface LogSegment {
  id: string
  type: LogSegmentType
  content: string
  language?: string  // terminal 专用
  isClosed: boolean
  toolName?: string   // tool 专用：工具名称
  toolDetail?: string // tool 专用：执行摘要
  taskStatus?: string // task 专用：任务状态
}

// 识别后端 _format_subagent_stream_chunk() 输出的 [前缀] 标记
const BRACKET_PREFIX_RE = /^\[(思考|工具|任务|状态|计划|错误)\]\s*([\s\S]*)$/

// 解析 [工具] name: detail 格式
function parseToolContent(raw: string): { toolName: string; toolDetail: string } {
  const colonIdx = raw.indexOf(':')
  if (colonIdx > 0) {
    return {
      toolName: raw.slice(0, colonIdx).trim(),
      toolDetail: raw.slice(colonIdx + 1).trim(),
    }
  }
  return { toolName: raw.trim(), toolDetail: '' }
}

// 解析 [任务] summary (status) 格式
function parseTaskStatus(raw: string): string {
  const match = raw.match(/\(([^)]+)\)\s*$/)
  return match ? match[1].trim() : 'completed'
}

export function parseSubagentLogs(logs: string): LogSegment[] {
  const segments: LogSegment[] = []
  let segCounter = 0

  // 按行处理，同时处理块级标记（<think> 和 ```）
  const lines = logs.split('\n')
  let lineIdx = 0

  // 累积文本行缓冲区
  let textBuffer: string[] = []
  // 块级状态：'none' | 'think' | 'terminal'
  let blockMode: 'none' | 'think' | 'terminal' = 'none'
  let blockBuffer: string[] = []
  let blockLanguage = ''

  const flushText = () => {
    const content = textBuffer.join('\n').trim()
    if (content) {
      segments.push({
        id: `seg-${segCounter++}`,
        type: 'text',
        content,
        isClosed: true,
      })
    }
    textBuffer = []
  }

  const flushBlock = (isClosed: boolean) => {
    const content = blockBuffer.join('\n')
    if (content.trim() || blockMode !== 'none') {
      segments.push({
        id: `seg-${segCounter++}`,
        type: blockMode === 'terminal' ? 'terminal' : 'think',
        content,
        language: blockMode === 'terminal' ? blockLanguage : undefined,
        isClosed,
      })
    }
    blockBuffer = []
    blockLanguage = ''
    blockMode = 'none'
  }

  while (lineIdx < lines.length) {
    const line = lines[lineIdx]
    lineIdx++

    if (blockMode === 'think') {
      // 等待 </think> 或 </thought>
      if (/^<\/(think|thought)>\s*$/i.test(line)) {
        flushBlock(true)
      } else {
        blockBuffer.push(line)
      }
      continue
    }

    if (blockMode === 'terminal') {
      // 等待单独的 ```
      if (/^```\s*$/.test(line)) {
        flushBlock(true)
      } else {
        blockBuffer.push(line)
      }
      continue
    }

    // 普通模式 - 检测块级开始标记
    if (/^(<think>|<thought>)\s*$/i.test(line)) {
      flushText()
      blockMode = 'think'
      blockBuffer = []
      continue
    }

    // <think>内容</think> 单行形式
    const inlineThinkMatch = line.match(/^(<think>|<thought>)([\s\S]*?)(<\/think>|<\/thought>)\s*$/i)
    if (inlineThinkMatch) {
      flushText()
      segments.push({
        id: `seg-${segCounter++}`,
        type: 'think',
        content: inlineThinkMatch[2],
        isClosed: true,
      })
      continue
    }

    const codeStartMatch = line.match(/^```([a-zA-Z0-9_-]*)\s*$/)
    if (codeStartMatch) {
      flushText()
      blockMode = 'terminal'
      blockLanguage = codeStartMatch[1] || ''
      blockBuffer = []
      continue
    }

    // 检测 [前缀] 标记行
    const prefixMatch = line.match(BRACKET_PREFIX_RE)
    if (prefixMatch) {
      flushText()
      const tag = prefixMatch[1]
      const rawContent = prefixMatch[2] || ''

      switch (tag) {
        case '思考': {
          // [思考] content 可能还跟着换行后的纯文本（来自 reasoning+content 合并）
          // 取当前行内容作为思维内容即可
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'think',
            content: rawContent,
            isClosed: true,
          })
          break
        }
        case '工具': {
          const { toolName, toolDetail } = parseToolContent(rawContent)
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'tool',
            content: rawContent,
            toolName,
            toolDetail,
            isClosed: true,
          })
          break
        }
        case '任务': {
          const taskStatus = parseTaskStatus(rawContent)
          const taskLabel = rawContent.replace(/\s*\([^)]+\)\s*$/, '').trim()
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'task',
            content: taskLabel || rawContent,
            taskStatus,
            isClosed: true,
          })
          break
        }
        case '状态': {
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'status',
            content: rawContent,
            isClosed: true,
          })
          break
        }
        case '计划': {
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'plan',
            content: rawContent,
            isClosed: true,
          })
          break
        }
        case '错误': {
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'error',
            content: rawContent,
            isClosed: true,
          })
          break
        }
      }
      continue
    }

    // 普通文本行
    textBuffer.push(line)
  }

  // 清空剩余缓冲
  if (blockMode !== 'none') {
    flushBlock(false)
  } else {
    flushText()
  }

  return segments
}