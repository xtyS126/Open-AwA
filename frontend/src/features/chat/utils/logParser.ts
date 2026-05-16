export type LogSegmentType = 'text' | 'think' | 'terminal' | 'tool' | 'task' | 'status' | 'plan' | 'error'

export interface LogSegment {
  id: string
  type: LogSegmentType
  content: string
  language?: string  // terminal 专用
  isClosed: boolean
  toolName?: string   // tool 专用：工具名称
  toolDetail?: string // tool 专用：执行摘要
  toolStatus?: string // tool 专用：工具状态
  taskStatus?: string // task 专用：任务状态
}

type StructuredPrefixTag = '思考' | '工具' | '任务' | '状态' | '计划' | '错误' | 'ERROR'

// 识别后端 _format_subagent_stream_chunk() 输出的 [前缀] 标记
const BRACKET_PREFIX_RE = /^\[(思考|工具|任务|状态|计划|错误|ERROR)\]\s*([\s\S]*)$/
const INLINE_PREFIX_RE = /\[(思考|工具|任务|状态|计划|错误|ERROR)\]/g
const SENTENCE_END_RE = /[。！？!?：:；;…]$/
const INLINE_MARKDOWN_PREFIX_RE = /^([#>*`-]|\d+\.)/
const THINK_CONTINUATION_PUNCTUATION_RE = /^[，。；：、,.;:）)】》]/
const THINK_CONTINUATION_WORDS = [
  '的',
  '地',
  '得',
  '了',
  '着',
  '从',
  '向',
  '在',
  '对',
  '给',
  '为',
  '被',
  '由',
  '因',
  '以',
  '并',
  '而',
  '且',
  '但',
  '或',
  '和',
  '与',
  '及',
]

function startsWithContinuationWord(content: string): boolean {
  const trimmed = content.trimStart()
  return THINK_CONTINUATION_WORDS.some((word) => trimmed.startsWith(word))
}

function shouldMergeTextIntoFollowingThink(current: LogSegment | undefined, next: LogSegment | undefined): boolean {
  if (!current || !next || current.type !== 'text' || next.type !== 'think') {
    return false
  }

  const currentContent = current.content.trim()
  const nextContent = next.content.trimStart()

  if (!currentContent || !nextContent) {
    return false
  }

  if (currentContent.length > 80 || currentContent.includes('\n') || currentContent.includes('\r')) {
    return false
  }

  if (SENTENCE_END_RE.test(currentContent) || INLINE_MARKDOWN_PREFIX_RE.test(currentContent)) {
    return false
  }

  return THINK_CONTINUATION_PUNCTUATION_RE.test(nextContent) || startsWithContinuationWord(nextContent)
}

function joinSplitSentence(left: string, right: string): string {
  const normalizedLeft = left.trimEnd()
  const normalizedRight = right.trimStart()

  if (!normalizedLeft) {
    return normalizedRight
  }

  if (!normalizedRight) {
    return normalizedLeft
  }

  if (/\s$/.test(left) || /^\s/.test(right)) {
    return normalizedLeft + normalizedRight
  }

  if (/[A-Za-z0-9_/-]$/.test(normalizedLeft) && /^[\u4e00-\u9fff]/.test(normalizedRight)) {
    return `${normalizedLeft} ${normalizedRight}`
  }

  return `${normalizedLeft}${normalizedRight}`
}

function normalizeSplitThinkSegments(segments: LogSegment[]): LogSegment[] {
  const normalized: LogSegment[] = []

  for (let index = 0; index < segments.length; index += 1) {
    const current = segments[index]
    const next = segments[index + 1]

    if (shouldMergeTextIntoFollowingThink(current, next)) {
      normalized.push({
        ...next,
        content: joinSplitSentence(current.content, next.content),
      })
      index += 1
      continue
    }

    normalized.push(current)
  }

  return normalized
}

function normalizeStructuredPrefixTag(tag: StructuredPrefixTag): Exclude<StructuredPrefixTag, 'ERROR'> | '错误' {
  return tag === 'ERROR' ? '错误' : tag
}

function splitInlineStructuredSegments(line: string): string[] {
  const matches = Array.from(line.matchAll(INLINE_PREFIX_RE))
  if (matches.length === 0) {
    return [line]
  }

  const parts: string[] = []
  for (let index = 0; index < matches.length; index += 1) {
    const currentMatch = matches[index]
    const currentIndex = currentMatch.index ?? 0
    const nextIndex = matches[index + 1]?.index ?? line.length

    if (index === 0 && currentIndex > 0) {
      parts.push(line.slice(0, currentIndex))
    }

    parts.push(line.slice(currentIndex, nextIndex))
  }

  return parts.filter((part) => part.length > 0)
}

function inferToolStatus(detail: string): string | undefined {
  const normalized = detail.trim().toLowerCase()
  if (!normalized) {
    return undefined
  }

  if (
    normalized === 'running'
    || normalized === 'in_progress'
    || normalized === '执行中'
    || normalized === '运行中'
    || normalized.includes('调用中')
  ) {
    return 'running'
  }

  if (
    normalized === 'completed'
    || normalized === 'done'
    || normalized === 'success'
    || normalized === '已完成'
    || normalized.includes('调用完成')
  ) {
    return 'completed'
  }

  if (
    normalized === 'error'
    || normalized === 'failed'
    || normalized === 'failure'
    || normalized === '失败'
    || normalized.includes('error')
  ) {
    return 'error'
  }

  if (normalized === 'pending' || normalized === 'queued' || normalized === '等待中') {
    return 'pending'
  }

  return undefined
}

// 解析 [工具] name: detail 格式
function parseToolContent(raw: string): { toolName: string; toolDetail: string; toolStatus?: string } {
  const colonIdx = raw.indexOf(':')
  if (colonIdx > 0) {
    const toolDetail = raw.slice(colonIdx + 1).trim()
    return {
      toolName: raw.slice(0, colonIdx).trim(),
      toolDetail,
      toolStatus: inferToolStatus(toolDetail),
    }
  }
  return { toolName: raw.trim(), toolDetail: '', toolStatus: undefined }
}

// 解析 [任务] summary (status) 格式
function parseTaskStatus(raw: string): string {
  const match = raw.match(/\(([^)]+)\)\s*$/)
  return match ? match[1].trim() : 'completed'
}

export function parseSubagentLogs(logs: string): LogSegment[] {
  const segments: LogSegment[] = []
  let segCounter = 0
  let lastPrefixTag: string | null = null

  // 按行处理，同时处理块级标记（<think> 和 ```）
  const lines = logs.split('\n')
  let lineIdx = 0
  const pendingInlineSegments: string[] = []

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

  while (pendingInlineSegments.length > 0 || lineIdx < lines.length) {
    let line = pendingInlineSegments.length > 0 ? pendingInlineSegments.shift() || '' : lines[lineIdx++]

    if (blockMode === 'think') {
      lastPrefixTag = null
      // 等待 </think> 或 </thought>
      if (/^<\/(think|thought)>\s*$/i.test(line)) {
        flushBlock(true)
      } else {
        blockBuffer.push(line)
      }
      continue
    }

    if (blockMode === 'terminal') {
      lastPrefixTag = null
      // 等待单独的 ```
      if (/^```\s*$/.test(line)) {
        flushBlock(true)
      } else {
        blockBuffer.push(line)
      }
      continue
    }

    const inlineSegments = splitInlineStructuredSegments(line)
    if (inlineSegments.length > 1) {
      line = inlineSegments[0]
      pendingInlineSegments.unshift(...inlineSegments.slice(1))
    }

    // 普通模式 - 检测块级开始标记
    if (/^(<think>|<thought>)\s*$/i.test(line)) {
      lastPrefixTag = null
      flushText()
      blockMode = 'think'
      blockBuffer = []
      continue
    }

    // <think>内容</think> 单行形式
    const inlineThinkMatch = line.match(/^(<think>|<thought>)([\s\S]*?)(<\/think>|<\/thought>)\s*$/i)
    if (inlineThinkMatch) {
      lastPrefixTag = null
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
      lastPrefixTag = null
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
      const tag = normalizeStructuredPrefixTag(prefixMatch[1] as StructuredPrefixTag)
      const rawContent = prefixMatch[2] || ''

      switch (tag) {
        case '思考': {
          const lastSegment = segments[segments.length - 1]
          if (lastPrefixTag === '思考' && lastSegment?.type === 'think') {
            lastSegment.content += rawContent
            break
          }
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'think',
            content: rawContent,
            isClosed: true,
          })
          break
        }
        case '工具': {
          const { toolName, toolDetail, toolStatus } = parseToolContent(rawContent)
          segments.push({
            id: `seg-${segCounter++}`,
            type: 'tool',
            content: rawContent,
            toolName,
            toolDetail,
            toolStatus,
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
      lastPrefixTag = tag
      continue
    }

    // 普通文本行
    lastPrefixTag = null
    textBuffer.push(line)
  }

  // 清空剩余缓冲
  if (blockMode !== 'none') {
    flushBlock(false)
  } else {
    flushText()
  }

  return normalizeSplitThinkSegments(segments)
}