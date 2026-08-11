declare const workbenchProjectIdBrand: unique symbol

/** 服务端生成的工作台项目不透明标识。 */
export type WorkbenchProjectId = string & {
  readonly [workbenchProjectIdBrand]: true
}

/** 在服务端响应边界把已验证的字符串收窄为项目标识。 */
export function asWorkbenchProjectId(value: string): WorkbenchProjectId {
  const normalized = value.trim()
  if (!normalized) {
    throw new Error('工作台项目 ID 不能为空')
  }
  return normalized as WorkbenchProjectId
}

/** 普通浏览器可见的项目摘要，不包含任何服务器绝对路径。 */
export interface WorkbenchProjectSummary {
  id: WorkbenchProjectId
  displayName: string
  isEnabled: boolean
  createdAt: string
  updatedAt: string
  lastOpenedAt: string | null
}

export interface WorkbenchContextResult {
  project: WorkbenchProjectSummary | null
  updatedAt: string | null
  etag: string | null
}

export interface WorkbenchProjectListResult {
  items: WorkbenchProjectSummary[]
}

export interface WorkbenchProjectCreateInput {
  displayName: string
  root: string
}

export interface WorkbenchProjectUpdateInput {
  displayName?: string
  isEnabled?: boolean
}

export type WorkbenchProjectPhase =
  | 'idle'
  | 'loading'
  | 'no-projects'
  | 'no-selection'
  | 'ready'
  | 'invalid'
  | 'switching'
  | 'error'

export type WorkbenchProjectSwitchBlocker =
  | { kind: 'dirty-files'; relativePaths: string[] }
  | { kind: 'git-operation'; operationId: string }
  | { kind: 'running-command'; sessionId: string }
  | { kind: 'active-agent-turn'; sessionId: string }

export interface WorkbenchPendingSwitch {
  fromProjectId: WorkbenchProjectId | null
  toProjectId: WorkbenchProjectId
  blockers: WorkbenchProjectSwitchBlocker[]
}

/** 首切片仅保存切换项目后仍需要恢复的编辑器内存状态。 */
export interface CodingProjectSnapshot {
  openFiles: Array<{
    path: string
    content: string
    isDirty: boolean
  }>
  activeFilePath: string | null
  activePanel: 'files' | 'editor' | 'chat'
}

export type WorkbenchPreviewIntent =
  | { kind: 'none' }
  | { kind: 'file'; relativePath: string }
  | { kind: 'web'; previewId: string }

export type WorkbenchTerminalBinding =
  | { kind: 'none' }
  | { kind: 'attached'; sessionId: string }

export interface WorkbenchRuntimeSnapshot {
  generation: number
  selectedAgentId: string | null
  selectedSessionId: string | null
  dockOpen: boolean
  dockPanel: 'terminal' | 'preview'
  terminalBinding: WorkbenchTerminalBinding
  previewIntent: WorkbenchPreviewIntent
}

export interface WorkbenchContextBroadcastMessage {
  type: 'context-changed'
  scopeKey: string
  etag: string | null
}
