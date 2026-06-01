/**
 * 工作区 API 调用模块。
 */
import api from '@/shared/api/api';

export const workspaceApi = {
  list: async (enabledOnly = false) => {
    const { data } = await api.get('/api/workspaces', {
      params: { enabled_only: enabledOnly },
    });
    return data;
  },

  get: async (workspaceId: string) => {
    const { data } = await api.get(`/api/workspaces/${workspaceId}`);
    return data;
  },

  create: async (body: { name: string; description?: string; agent_type?: string }) => {
    const { data } = await api.post('/api/workspaces', body);
    return data;
  },

  update: async (workspaceId: string, body: Record<string, unknown>) => {
    const { data } = await api.put(`/api/workspaces/${workspaceId}`, body);
    return data;
  },

  delete: async (workspaceId: string) => {
    const { data } = await api.delete(`/api/workspaces/${workspaceId}`);
    return data;
  },
};
