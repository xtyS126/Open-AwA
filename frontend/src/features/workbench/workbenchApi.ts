import type { AxiosResponse } from 'axios'
import { api } from '@/shared/api/client'
import {
  asWorkbenchProjectId,
  type WorkbenchContextResult,
  type WorkbenchProjectCreateInput,
  type WorkbenchProjectListResult,
  type WorkbenchProjectSummary,
  type WorkbenchProjectUpdateInput,
  type WorkbenchProjectId,
} from './workbenchTypes'

const BASE = '/workbench'

interface ProjectSummaryResponse {
  id: string
  display_name: string
  is_enabled: boolean
  created_at: string
  updated_at: string
  last_opened_at: string | null
}

interface ProjectListResponse {
  items: ProjectSummaryResponse[]
}

interface ContextResponse {
  project: ProjectSummaryResponse | null
  updated_at: string | null
}

function mapProject(response: ProjectSummaryResponse): WorkbenchProjectSummary {
  return {
    id: asWorkbenchProjectId(response.id),
    displayName: response.display_name,
    isEnabled: response.is_enabled,
    createdAt: response.created_at,
    updatedAt: response.updated_at,
    lastOpenedAt: response.last_opened_at,
  }
}

function readEtag(response: AxiosResponse<unknown>): string | null {
  const value = response.headers?.etag ?? response.headers?.ETag
  return typeof value === 'string' && value ? value : null
}

function mapContext(response: AxiosResponse<ContextResponse>): WorkbenchContextResult {
  return {
    project: response.data.project ? mapProject(response.data.project) : null,
    updatedAt: response.data.updated_at,
    etag: readEtag(response),
  }
}

export const workbenchApi = {
  async listProjects(signal?: AbortSignal): Promise<WorkbenchProjectListResult> {
    const response = await api.get<ProjectListResponse>(`${BASE}/projects`, { signal })
    return { items: response.data.items.map(mapProject) }
  },

  async getContext(signal?: AbortSignal): Promise<WorkbenchContextResult> {
    const response = await api.get<ContextResponse>(`${BASE}/context`, { signal })
    return mapContext(response)
  },

  async createProject(input: WorkbenchProjectCreateInput): Promise<WorkbenchProjectSummary> {
    const response = await api.post<ProjectSummaryResponse>(`${BASE}/projects`, {
      display_name: input.displayName,
      root: input.root,
    })
    return mapProject(response.data)
  },

  async updateProject(
    projectId: WorkbenchProjectId,
    input: WorkbenchProjectUpdateInput,
  ): Promise<WorkbenchProjectSummary> {
    const body: Record<string, unknown> = {}
    if (input.displayName !== undefined) body.display_name = input.displayName
    if (input.isEnabled !== undefined) body.is_enabled = input.isEnabled
    const response = await api.patch<ProjectSummaryResponse>(
      `${BASE}/projects/${encodeURIComponent(projectId)}`,
      body,
    )
    return mapProject(response.data)
  },

  async deleteProject(projectId: WorkbenchProjectId): Promise<void> {
    await api.delete(`${BASE}/projects/${encodeURIComponent(projectId)}`)
  },

  async patchContext(
    projectId: WorkbenchProjectId | null,
    etag: string | null,
  ): Promise<WorkbenchContextResult> {
    const headers = etag ? { 'If-Match': etag } : undefined
    const response = await api.patch<ContextResponse>(
      `${BASE}/context`,
      { project_id: projectId },
      headers ? { headers } : undefined,
    )
    return mapContext(response)
  },
}

interface ErrorResponseShape {
  response?: {
    status?: number
    data?: {
      detail?: unknown
      error?: unknown
      message?: unknown
    }
  }
}

function getErrorCode(error: unknown): string | null {
  const data = (error as ErrorResponseShape)?.response?.data
  const detail = data?.detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code
    return typeof code === 'string' ? code : null
  }
  if (typeof data?.error === 'string') return data.error
  return null
}

export function isWorkbenchContextConflict(error: unknown): boolean {
  const status = (error as ErrorResponseShape)?.response?.status
  return status === 409 && getErrorCode(error) === 'workbench_context_version_conflict'
}

export function getWorkbenchErrorMessage(error: unknown): string {
  const code = getErrorCode(error)
  const messages: Record<string, string> = {
    workbench_project_not_found: '项目不存在或无权访问，请刷新项目列表',
    workbench_project_root_conflict: '该目录已经登记，请选择现有项目',
    workbench_project_in_use: '项目仍有运行中资源，请先关闭终端或 Agent 会话',
    workbench_project_disabled: '项目已禁用，请先启用后再使用',
    workbench_project_root_invalid: '项目路径无效，请检查路径是否存在且为目录',
    workbench_project_root_forbidden: '项目路径不在服务器允许范围内',
    workbench_context_version_conflict: '项目上下文已在其他标签页更新，正在刷新',
  }
  if (code && messages[code]) return messages[code]

  const detail = (error as ErrorResponseShape)?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  if (error instanceof Error && error.message.trim()) return error.message
  return '工作台请求失败，请稍后重试'
}
