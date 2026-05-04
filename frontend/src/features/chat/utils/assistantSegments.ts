import type {
  AssistantExecutionMeta,
  AssistantMessageSegment,
  AssistantThoughtSegment,
  TaskStepMeta,
  ToolEventMeta,
  UsageMeta,
} from '@/features/chat/types'

function createSegmentId(prefix: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function cloneThoughtSegment(segment: AssistantThoughtSegment): AssistantThoughtSegment {
  return {
    ...segment,
    toolEvents: [...segment.toolEvents],
    steps: [...segment.steps],
  }
}

function cloneSegments(segments: AssistantMessageSegment[] | undefined): AssistantMessageSegment[] {
  if (!segments || segments.length === 0) {
    return []
  }
  return segments.map((segment) => (
    segment.kind === 'thought'
      ? cloneThoughtSegment(segment)
      : { ...segment }
  ))
}

function createThoughtSegment(): AssistantThoughtSegment {
  return {
    id: createSegmentId('thought'),
    kind: 'thought',
    reasoningContent: '',
    toolEvents: [],
    steps: [],
    status: 'running',
  }
}

function createReplySegment(content: string): AssistantMessageSegment {
  return {
    id: createSegmentId('reply'),
    kind: 'reply',
    content,
  }
}

function getLastThoughtIndex(segments: AssistantMessageSegment[]): number {
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    if (segments[index]?.kind === 'thought') {
      return index
    }
  }
  return -1
}

function ensureCurrentThoughtSegment(
  segments: AssistantMessageSegment[],
  startNewIfHasTools: boolean = false
): AssistantThoughtSegment {
  const lastSegment = segments[segments.length - 1]
  if (!lastSegment || lastSegment.kind === 'reply') {
    const nextSegment = createThoughtSegment()
    segments.push(nextSegment)
    return nextSegment
  }
  
  if (lastSegment.kind === 'thought') {
    if (startNewIfHasTools && (lastSegment.toolEvents.length > 0 || lastSegment.steps.length > 0)) {
      lastSegment.status = 'completed'
      const nextSegment = createThoughtSegment()
      segments.push(nextSegment)
      return nextSegment
    }
  }
  
  return lastSegment as AssistantThoughtSegment
}

function upsertToolEvent(toolEvents: ToolEventMeta[], tool: ToolEventMeta): ToolEventMeta[] {
  const existingIndex = toolEvents.findIndex((item) => item.id === tool.id)
  if (existingIndex < 0) {
    return [...toolEvents, tool]
  }
  const nextToolEvents = [...toolEvents]
  nextToolEvents[existingIndex] = {
    ...nextToolEvents[existingIndex],
    ...tool,
  }
  return nextToolEvents
}

function patchToolEvent(
  toolEvents: ToolEventMeta[],
  toolId: string,
  patch: Partial<ToolEventMeta>
): ToolEventMeta[] {
  const existingIndex = toolEvents.findIndex((item) => item.id === toolId)
  if (existingIndex < 0) {
    return toolEvents
  }
  const nextToolEvents = [...toolEvents]
  nextToolEvents[existingIndex] = {
    ...nextToolEvents[existingIndex],
    ...patch,
  }
  return nextToolEvents
}

function upsertStep(steps: TaskStepMeta[], step: TaskStepMeta): TaskStepMeta[] {
  const existingIndex = steps.findIndex((item) => item.step === step.step && item.action === step.action)
  if (existingIndex < 0) {
    return [...steps, step]
  }
  const nextSteps = [...steps]
  nextSteps[existingIndex] = {
    ...nextSteps[existingIndex],
    ...step,
  }
  return nextSteps
}

export function appendAssistantChunk(
  segments: AssistantMessageSegment[] | undefined,
  payload: {
    content?: string
    reasoningContent?: string
  }
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const reasoningContent = payload.reasoningContent || ''
  const content = payload.content || ''

  if (reasoningContent) {
    const thoughtSegment = ensureCurrentThoughtSegment(nextSegments, true)
    thoughtSegment.reasoningContent += reasoningContent
    thoughtSegment.status = 'running'
  }

  if (content) {
    const lastSegment = nextSegments[nextSegments.length - 1]
    if (lastSegment?.kind === 'reply') {
      lastSegment.content += content
    } else {
      if (lastSegment?.kind === 'thought') {
        lastSegment.status = 'completed'
      }
      nextSegments.push(createReplySegment(content))
    }
  }

  return nextSegments
}

export function applyToolEventToSegments(
  segments: AssistantMessageSegment[] | undefined,
  tool: ToolEventMeta
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const thoughtSegment = ensureCurrentThoughtSegment(nextSegments)
  thoughtSegment.toolEvents = upsertToolEvent(thoughtSegment.toolEvents, tool)
  thoughtSegment.status = tool.status === 'completed' && thoughtSegment.status === 'completed' ? 'completed' : 'running'
  return nextSegments
}

export function applyToolPatchToSegments(
  segments: AssistantMessageSegment[] | undefined,
  toolId: string,
  patch: Partial<ToolEventMeta>
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const lastThoughtIndex = getLastThoughtIndex(nextSegments)
  if (lastThoughtIndex < 0) {
    return nextSegments
  }
  const thoughtSegment = nextSegments[lastThoughtIndex] as AssistantThoughtSegment
  thoughtSegment.toolEvents = patchToolEvent(thoughtSegment.toolEvents, toolId, patch)
  return nextSegments
}

export function applyStepToSegments(
  segments: AssistantMessageSegment[] | undefined,
  step: TaskStepMeta
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const thoughtSegment = ensureCurrentThoughtSegment(nextSegments)
  thoughtSegment.steps = upsertStep(thoughtSegment.steps, step)
  if (step.status !== 'completed') {
    thoughtSegment.status = 'running'
  }
  return nextSegments
}

export function applyUsageToSegments(
  segments: AssistantMessageSegment[] | undefined,
  usage: UsageMeta
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const lastThoughtIndex = getLastThoughtIndex(nextSegments)
  if (lastThoughtIndex < 0) {
    return nextSegments
  }
  const thoughtSegment = nextSegments[lastThoughtIndex] as AssistantThoughtSegment
  thoughtSegment.usage = usage
  return nextSegments
}

export function applyIntentToSegments(
  segments: AssistantMessageSegment[] | undefined,
  intent: string
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  const thoughtSegment = ensureCurrentThoughtSegment(nextSegments)
  thoughtSegment.intent = intent
  return nextSegments
}

export function finalizeAssistantSegments(
  segments: AssistantMessageSegment[] | undefined
): AssistantMessageSegment[] {
  const nextSegments = cloneSegments(segments)
  for (const segment of nextSegments) {
    if (segment.kind === 'thought') {
      segment.status = 'completed'
    }
  }
  return nextSegments
}

export function buildSegmentsFromLegacyMessage(payload: {
  content?: string
  reasoningContent?: string
  meta?: AssistantExecutionMeta
}): AssistantMessageSegment[] {
  let segments: AssistantMessageSegment[] = []
  const { content, reasoningContent, meta } = payload

  if (reasoningContent) {
    segments = appendAssistantChunk(segments, { reasoningContent })
  }
  if (meta?.intent) {
    segments = applyIntentToSegments(segments, meta.intent)
  }
  if (meta?.steps) {
    for (const step of meta.steps) {
      segments = applyStepToSegments(segments, step)
    }
  }
  if (meta?.toolEvents) {
    for (const tool of meta.toolEvents) {
      segments = applyToolEventToSegments(segments, tool)
    }
  }
  if (meta?.usage) {
    segments = applyUsageToSegments(segments, meta.usage)
  }
  if (content) {
    segments = appendAssistantChunk(segments, { content })
  }

  return finalizeAssistantSegments(segments)
}
