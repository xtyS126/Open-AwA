/**
 * 工作区 API 调用模块。
 * 类型与 backend/api/routes/workspace.py 中的响应结构保持一致。
 */
import api from '@/shared/api/api';

/** 工作区列表项：与 backend list_workspaces 返回字段一致。 */
export interface WorkspaceItem {
  id: string;
  name: string;
  description: string;
  agent_type: string;
  is_default: boolean;
  is_enabled: boolean;
  skills_count: number;
  channels_count: number;
  created_at: string | null;
  updated_at: string | null;
}

/** 工作区列表响应。 */
export interface WorkspaceListResponse {
  workspaces: WorkspaceItem[];
}

/** 创建工作区请求体。 */
export interface WorkspaceCreatePayload {
  name: string;
  description?: string;
  agent_type?: string;
  workspace_id?: string;
}

/** 更新工作区请求体：与 backend WorkspaceUpdate 对齐。 */
export interface WorkspaceUpdatePayload {
  name?: string;
  description?: string;
  agent_type?: string;
  is_enabled?: boolean;
  config_json?: Record<string, unknown>;
  enabled_channels_json?: Record<string, unknown>;
}

export const workspaceApi = {
  /** 获取工作区列表，可选仅返回已启用项。 */
  list: async (enabledOnly = false): Promise<WorkspaceListResponse> => {
    const { data } = await api.get<WorkspaceListResponse>('/workspaces', {
      params: { enabled_only: enabledOnly },
    });
    return data;
  },

  /** 获取单个工作区详情。 */
  get: async (workspaceId: string): Promise<WorkspaceItem> => {
    const { data } = await api.get<WorkspaceItem>(`/workspaces/${workspaceId}`);
    return data;
  },

  /** 创建新工作区。 */
  create: async (body: WorkspaceCreatePayload): Promise<WorkspaceItem> => {
    const { data } = await api.post<WorkspaceItem>('/workspaces', body);
    return data;
  },

  /** 更新工作区配置。 */
  update: async (workspaceId: string, body: WorkspaceUpdatePayload): Promise<WorkspaceItem> => {
    const { data } = await api.put<WorkspaceItem>(`/workspaces/${workspaceId}`, body);
    return data;
  },

  /** 删除工作区。 */
  delete: async (workspaceId: string): Promise<{ message: string }> => {
    const { data } = await api.delete<{ message: string }>(`/workspaces/${workspaceId}`);
    return data;
  },
};
