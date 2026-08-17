import api from '@/shared/api/api'

export type WorkbenchPreviewSessionKind = 'terminal' | 'acp'

export interface WorkbenchPreviewCreateInput {
  sessionKind: WorkbenchPreviewSessionKind
  sessionId: string
  port: number
}

export interface WorkbenchPreviewLease {
  previewId: string
  projectId: string
  sessionKind: WorkbenchPreviewSessionKind
  sessionId: string
  expiresAt: string
}

interface WorkbenchPreviewLeaseResponse {
  preview_id: string
  project_id: string
  session_kind: WorkbenchPreviewSessionKind
  session_id: string
  expires_at: string
}

function mapLease(response: WorkbenchPreviewLeaseResponse): WorkbenchPreviewLease {
  return {
    previewId: response.preview_id,
    projectId: response.project_id,
    sessionKind: response.session_kind,
    sessionId: response.session_id,
    expiresAt: response.expires_at,
  }
}

export const workbenchPreviewApi = {
  async create(
    projectId: string,
    input: WorkbenchPreviewCreateInput,
  ): Promise<WorkbenchPreviewLease> {
    const { data } = await api.post<WorkbenchPreviewLeaseResponse>(
      `/workbench/projects/${encodeURIComponent(projectId)}/previews`,
      {
        session_kind: input.sessionKind,
        session_id: input.sessionId,
        port: input.port,
      },
    )
    return mapLease(data)
  },

  async renew(projectId: string, previewId: string): Promise<WorkbenchPreviewLease> {
    const { data } = await api.post<WorkbenchPreviewLeaseResponse>(
      `/workbench/projects/${encodeURIComponent(projectId)}/previews/${encodeURIComponent(previewId)}/renew`,
    )
    return mapLease(data)
  },

  async revoke(projectId: string, previewId: string): Promise<void> {
    await api.delete(
      `/workbench/projects/${encodeURIComponent(projectId)}/previews/${encodeURIComponent(previewId)}`,
    )
  },
}
