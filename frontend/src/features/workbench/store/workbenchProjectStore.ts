import { createWithEqualityFn } from 'zustand/traditional'
import {
  getWorkbenchErrorMessage,
  isWorkbenchContextConflict,
  workbenchApi,
} from '../workbenchApi'
import type {
  CodingProjectSnapshot,
  WorkbenchContextBroadcastMessage,
  WorkbenchPendingSwitch,
  WorkbenchProjectId,
  WorkbenchProjectPhase,
  WorkbenchProjectSummary,
} from '../workbenchTypes'
import { useWorkbenchRuntimeStore } from './workbenchRuntimeStore'

export const WORKBENCH_CONTEXT_CHANNEL = 'openawa-workbench-context'

interface HydrateOptions {
  force?: boolean
}

interface WorkbenchProjectStore {
  projects: WorkbenchProjectSummary[]
  currentProjectId: WorkbenchProjectId | null
  phase: WorkbenchProjectPhase
  error: string | null
  contextEtag: string | null
  activeScopeKey: string | null
  pendingSwitch: WorkbenchPendingSwitch | null
  switchGeneration: number
  requestEpoch: number
  codingSnapshots: Record<string, CodingProjectSnapshot>
  hydrate: (scopeKey: string, options?: HydrateOptions) => Promise<void>
  selectProject: (projectId: WorkbenchProjectId) => Promise<void>
  clearProject: () => Promise<void>
  confirmSwitch: () => Promise<void>
  cancelSwitch: () => void
  resetForServerChange: () => void
}

const hydrationRequests = new Map<string, Promise<void>>()

function projectPhase(
  projects: WorkbenchProjectSummary[],
  current: WorkbenchProjectSummary | null,
): WorkbenchProjectPhase {
  if (projects.length === 0) return 'no-projects'
  if (!current) return 'no-selection'
  return current.isEnabled ? 'ready' : 'invalid'
}

function mergeProject(
  projects: WorkbenchProjectSummary[],
  project: WorkbenchProjectSummary,
): WorkbenchProjectSummary[] {
  const index = projects.findIndex((item) => item.id === project.id)
  if (index < 0) return [...projects, project]
  return projects.map((item, itemIndex) => itemIndex === index ? project : item)
}

function broadcastContextChanged(scopeKey: string, etag: string | null): void {
  if (typeof BroadcastChannel === 'undefined') return
  const channel = new BroadcastChannel(WORKBENCH_CONTEXT_CHANNEL)
  const message: WorkbenchContextBroadcastMessage = {
    type: 'context-changed',
    scopeKey,
    etag,
  }
  channel.postMessage(message)
  channel.close()
}

const initialState = () => ({
  projects: [] as WorkbenchProjectSummary[],
  currentProjectId: null as WorkbenchProjectId | null,
  phase: 'idle' as WorkbenchProjectPhase,
  error: null as string | null,
  contextEtag: null as string | null,
  activeScopeKey: null as string | null,
  pendingSwitch: null as WorkbenchPendingSwitch | null,
  switchGeneration: 0,
  requestEpoch: 0,
  codingSnapshots: {} as Record<string, CodingProjectSnapshot>,
})

export const useWorkbenchProjectStore = createWithEqualityFn<WorkbenchProjectStore>((set, get) => ({
  ...initialState(),

  hydrate: (scopeKey, options = {}) => {
    const existing = hydrationRequests.get(scopeKey)
    if (existing) return existing

    const current = get()
    if (!options.force && current.activeScopeKey === scopeKey && current.phase !== 'idle' && current.phase !== 'error') {
      return Promise.resolve()
    }

    const nextEpoch = current.requestEpoch + 1
    const scopeChanged = current.activeScopeKey !== scopeKey
    set(scopeChanged
      ? {
          ...initialState(),
          activeScopeKey: scopeKey,
          requestEpoch: nextEpoch,
          phase: 'loading',
        }
      : {
          requestEpoch: nextEpoch,
          phase: current.phase === 'idle' ? 'loading' : current.phase,
          error: null,
        })

    let request: Promise<void>
    request = Promise.all([
      workbenchApi.listProjects(),
      workbenchApi.getContext(),
    ]).then(([list, context]) => {
      const latest = get()
      if (latest.activeScopeKey !== scopeKey || latest.requestEpoch !== nextEpoch) return
      const projects = context.project
        ? mergeProject(list.items, context.project)
        : list.items
      const nextProjectId = context.project?.id ?? null
      set({
        projects,
        currentProjectId: nextProjectId,
        contextEtag: context.etag,
        switchGeneration: latest.switchGeneration + (latest.currentProjectId === nextProjectId ? 0 : 1),
        phase: projectPhase(projects, context.project),
        error: null,
      })
    }).catch((error: unknown) => {
      const latest = get()
      if (latest.activeScopeKey === scopeKey && latest.requestEpoch === nextEpoch) {
        set({ phase: 'error', error: getWorkbenchErrorMessage(error) })
      }
      throw error
    }).finally(() => {
      if (hydrationRequests.get(scopeKey) === request) {
        hydrationRequests.delete(scopeKey)
      }
    })
    hydrationRequests.set(scopeKey, request)
    return request
  },

  selectProject: async (projectId) => {
    const before = get()
    if (before.currentProjectId === projectId && before.phase === 'ready') return
    const scopeKey = before.activeScopeKey
    const epoch = before.requestEpoch
    const previousPhase = before.phase
    set({ phase: 'switching', error: null })
    try {
      const context = await workbenchApi.patchContext(projectId, before.contextEtag)
      const latest = get()
      if (latest.activeScopeKey !== scopeKey || latest.requestEpoch !== epoch) return
      const projects = context.project
        ? mergeProject(latest.projects, context.project)
        : latest.projects
      set({
        projects,
        currentProjectId: context.project?.id ?? null,
        contextEtag: context.etag,
        switchGeneration: latest.switchGeneration + 1,
        phase: projectPhase(projects, context.project),
        pendingSwitch: null,
        error: null,
      })
      if (scopeKey) broadcastContextChanged(scopeKey, context.etag)
    } catch (error) {
      const latest = get()
      if (latest.activeScopeKey === scopeKey && latest.requestEpoch === epoch) {
        set({ phase: previousPhase, error: getWorkbenchErrorMessage(error) })
        if (scopeKey && isWorkbenchContextConflict(error)) {
          void get().hydrate(scopeKey, { force: true }).catch(() => undefined)
        }
      }
      throw error
    }
  },

  clearProject: async () => {
    const before = get()
    const scopeKey = before.activeScopeKey
    const epoch = before.requestEpoch
    const previousPhase = before.phase
    set({ phase: 'switching', error: null })
    try {
      const context = await workbenchApi.patchContext(null, before.contextEtag)
      const latest = get()
      if (latest.activeScopeKey !== scopeKey || latest.requestEpoch !== epoch) return
      set({
        currentProjectId: null,
        contextEtag: context.etag,
        switchGeneration: latest.switchGeneration + 1,
        phase: latest.projects.length > 0 ? 'no-selection' : 'no-projects',
        pendingSwitch: null,
        error: null,
      })
      if (scopeKey) broadcastContextChanged(scopeKey, context.etag)
    } catch (error) {
      const latest = get()
      if (latest.activeScopeKey === scopeKey && latest.requestEpoch === epoch) {
        set({ phase: previousPhase, error: getWorkbenchErrorMessage(error) })
      }
      throw error
    }
  },

  confirmSwitch: async () => {
    const pending = get().pendingSwitch
    if (!pending) return
    await get().selectProject(pending.toProjectId)
  },

  cancelSwitch: () => set({ pendingSwitch: null }),

  resetForServerChange: () => {
    hydrationRequests.clear()
    useWorkbenchRuntimeStore.getState().resetAll()
    const nextEpoch = get().requestEpoch + 1
    set({ ...initialState(), requestEpoch: nextEpoch })
  },
}))

export function selectCurrentWorkbenchProject(
  state: WorkbenchProjectStore,
): WorkbenchProjectSummary | null {
  if (!state.currentProjectId) return null
  return state.projects.find((project) => project.id === state.currentProjectId) ?? null
}
