/**
 * 工作区 Zustand 状态管理。
 */
import { createWithEqualityFn } from 'zustand/traditional';

export interface Workspace {
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

interface WorkspaceStore {
  workspaces: Workspace[];
  currentWorkspaceId: string;
  setWorkspaces: (workspaces: Workspace[]) => void;
  setCurrentWorkspace: (workspaceId: string) => void;
}

export const useWorkspaceStore = createWithEqualityFn<WorkspaceStore>((set) => ({
  workspaces: [],
  currentWorkspaceId: 'default',
  setWorkspaces: (workspaces) => set({ workspaces }),
  setCurrentWorkspace: (workspaceId) => {
    localStorage.setItem('openawa_workspace_id', workspaceId);
    set({ currentWorkspaceId: workspaceId });
  },
}));

// 初始化当前工作区（仅在浏览器环境下）
if (typeof window !== 'undefined') {
  const saved = localStorage.getItem('openawa_workspace_id');
  if (saved) {
    useWorkspaceStore.getState().setCurrentWorkspace(saved);
  }
}
