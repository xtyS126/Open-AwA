import { createWithEqualityFn } from 'zustand/traditional'
import type {
  WorkbenchPreviewIntent,
  WorkbenchProjectId,
  WorkbenchRuntimeSnapshot,
  WorkbenchTerminalBinding,
} from '../workbenchTypes'

interface WorkbenchRuntimeStore {
  projects: Record<string, WorkbenchRuntimeSnapshot>
  activateProject: (projectId: WorkbenchProjectId, generation: number) => void
  setSelectedAgent: (
    projectId: WorkbenchProjectId,
    generation: number,
    agentId: string | null,
  ) => void
  setSelectedSession: (
    projectId: WorkbenchProjectId,
    generation: number,
    sessionId: string | null,
  ) => void
  setDockState: (
    projectId: WorkbenchProjectId,
    generation: number,
    state: { open?: boolean; panel?: 'terminal' | 'preview' },
  ) => void
  setTerminalBinding: (
    projectId: WorkbenchProjectId,
    generation: number,
    binding: WorkbenchTerminalBinding,
  ) => void
  setPreviewIntent: (
    projectId: WorkbenchProjectId,
    generation: number,
    intent: WorkbenchPreviewIntent,
  ) => void
  clearProject: (projectId: WorkbenchProjectId) => void
  resetAll: () => void
}

function createRuntime(generation: number): WorkbenchRuntimeSnapshot {
  return {
    generation,
    selectedAgentId: null,
    selectedSessionId: null,
    dockOpen: false,
    dockPanel: 'terminal',
    terminalBinding: { kind: 'none' },
    previewIntent: { kind: 'none' },
  }
}

export const useWorkbenchRuntimeStore = createWithEqualityFn<WorkbenchRuntimeStore>((set) => ({
  projects: {},

  activateProject: (projectId, generation) => set((state) => {
    const existing = state.projects[projectId]
    if (existing && generation < existing.generation) return state
    if (existing?.generation === generation) return state
    return {
      projects: {
        ...state.projects,
        [projectId]: existing
          ? {
              ...existing,
              generation,
              terminalBinding: { kind: 'none' },
              previewIntent: { kind: 'none' },
            }
          : createRuntime(generation),
      },
    }
  }),

  setSelectedAgent: (projectId, generation, selectedAgentId) => set((state) => {
    const runtime = state.projects[projectId]
    if (!runtime || runtime.generation !== generation) return state
    return { projects: { ...state.projects, [projectId]: { ...runtime, selectedAgentId } } }
  }),

  setSelectedSession: (projectId, generation, selectedSessionId) => set((state) => {
    const runtime = state.projects[projectId]
    if (!runtime || runtime.generation !== generation) return state
    return { projects: { ...state.projects, [projectId]: { ...runtime, selectedSessionId } } }
  }),

  setDockState: (projectId, generation, dockState) => set((state) => {
    const runtime = state.projects[projectId]
    if (!runtime || runtime.generation !== generation) return state
    return {
      projects: {
        ...state.projects,
        [projectId]: {
          ...runtime,
          dockOpen: dockState.open ?? runtime.dockOpen,
          dockPanel: dockState.panel ?? runtime.dockPanel,
        },
      },
    }
  }),

  setTerminalBinding: (projectId, generation, terminalBinding) => set((state) => {
    const runtime = state.projects[projectId]
    if (!runtime || runtime.generation !== generation) return state
    return { projects: { ...state.projects, [projectId]: { ...runtime, terminalBinding } } }
  }),

  setPreviewIntent: (projectId, generation, previewIntent) => set((state) => {
    const runtime = state.projects[projectId]
    if (!runtime || runtime.generation !== generation) return state
    return { projects: { ...state.projects, [projectId]: { ...runtime, previewIntent } } }
  }),

  clearProject: (projectId) => set((state) => {
    const projects = { ...state.projects }
    delete projects[projectId]
    return { projects }
  }),

  resetAll: () => set({ projects: {} }),
}))
