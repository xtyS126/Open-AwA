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
import {
  abortWorkbenchPreparedProjectSwitches,
  collectWorkbenchProjectSwitchBlockers,
  commitWorkbenchPreparedProjectSwitches,
  prepareWorkbenchProjectSwitchParticipants,
  syncWorkbenchCommittedProject,
  type WorkbenchProjectSwitchDecision,
} from '../workbenchProjectSwitchCoordinator'

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
  selectProject: (
    projectId: WorkbenchProjectId,
    decision?: WorkbenchProjectSwitchDecision,
  ) => Promise<void>
  clearProject: () => Promise<void>
  confirmSwitch: (decision: WorkbenchProjectSwitchDecision) => Promise<void>
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

function activateRuntimeProject(
  projectId: WorkbenchProjectId | null,
  generation: number,
): void {
  if (projectId) {
    useWorkbenchRuntimeStore.getState().activateProject(projectId, generation)
  }
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
      const nextGeneration = latest.switchGeneration + (latest.currentProjectId === nextProjectId ? 0 : 1)
      set({
        projects,
        currentProjectId: nextProjectId,
        contextEtag: context.etag,
        switchGeneration: nextGeneration,
        phase: projectPhase(projects, context.project),
        error: null,
      })
      syncWorkbenchCommittedProject(nextProjectId, nextGeneration)
      activateRuntimeProject(nextProjectId, nextGeneration)
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

  selectProject: async (projectId, decision) => {
    const before = get()
    if (before.currentProjectId === projectId && before.phase === 'ready') return
    const blockers = collectWorkbenchProjectSwitchBlockers(before.currentProjectId, projectId)
    const unresolvedBlockers = blockers.filter((blocker) => (
      blocker.kind !== 'dirty-files' || decision === undefined
    ))
    if (unresolvedBlockers.length > 0) {
      set({
        pendingSwitch: {
          fromProjectId: before.currentProjectId,
          toProjectId: projectId,
          blockers: unresolvedBlockers,
        },
        error: null,
      })
      return
    }
    const scopeKey = before.activeScopeKey
    const epoch = before.requestEpoch
    const previousPhase = before.phase
    set({ phase: 'switching', error: null })
    let prepared = [] as Awaited<ReturnType<typeof prepareWorkbenchProjectSwitchParticipants>>
    let committedContext: Awaited<ReturnType<typeof workbenchApi.patchContext>> | null = null
    try {
      prepared = await prepareWorkbenchProjectSwitchParticipants(
        before.currentProjectId,
        projectId,
        decision,
      )
      const context = await workbenchApi.patchContext(projectId, before.contextEtag)
      committedContext = context
      const latest = get()
      if (latest.activeScopeKey !== scopeKey || latest.requestEpoch !== epoch) {
        await abortWorkbenchPreparedProjectSwitches(prepared)
        return
      }
      const projects = context.project
        ? mergeProject(latest.projects, context.project)
        : latest.projects
      const nextGeneration = latest.switchGeneration + 1
      set({
        projects,
        currentProjectId: context.project?.id ?? null,
        contextEtag: context.etag,
        switchGeneration: nextGeneration,
        phase: projectPhase(projects, context.project),
        pendingSwitch: null,
        error: null,
      })
      activateRuntimeProject(context.project?.id ?? null, nextGeneration)
      await commitWorkbenchPreparedProjectSwitches(prepared, nextGeneration)
      if (scopeKey) broadcastContextChanged(scopeKey, context.etag)
    } catch (error) {
      let compensation: Awaited<ReturnType<typeof workbenchApi.patchContext>> | null = null
      if (committedContext) {
        try {
          compensation = await workbenchApi.patchContext(
            before.currentProjectId,
            committedContext.etag,
          )
        } catch (compensationError) {
          await abortWorkbenchPreparedProjectSwitches(prepared)
          const latest = get()
          if (latest.activeScopeKey === scopeKey && latest.requestEpoch === epoch) {
            set({ phase: 'error', error: getWorkbenchErrorMessage(compensationError) })
            if (scopeKey) {
              await get().hydrate(scopeKey, { force: true }).catch(() => undefined)
            }
          }
          throw error
        }
      }
      await abortWorkbenchPreparedProjectSwitches(prepared)
      const latest = get()
      if (latest.activeScopeKey === scopeKey && latest.requestEpoch === epoch) {
        const compensatedProjects = compensation?.project
          ? mergeProject(latest.projects, compensation.project)
          : latest.projects
        set({
          projects: compensatedProjects,
          currentProjectId: compensation
            ? compensation.project?.id ?? null
            : before.currentProjectId,
          contextEtag: compensation?.etag ?? before.contextEtag,
          switchGeneration: compensation
            ? latest.switchGeneration + 1
            : latest.switchGeneration,
          phase: compensation
            ? projectPhase(compensatedProjects, compensation.project)
            : previousPhase,
          error: getWorkbenchErrorMessage(error),
        })
        activateRuntimeProject(
          compensation ? compensation.project?.id ?? null : before.currentProjectId,
          compensation ? latest.switchGeneration + 1 : latest.switchGeneration,
        )
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
      const nextGeneration = latest.switchGeneration + 1
      set({
        currentProjectId: null,
        contextEtag: context.etag,
        switchGeneration: nextGeneration,
        phase: latest.projects.length > 0 ? 'no-selection' : 'no-projects',
        pendingSwitch: null,
        error: null,
      })
      syncWorkbenchCommittedProject(null, nextGeneration)
      if (scopeKey) broadcastContextChanged(scopeKey, context.etag)
    } catch (error) {
      const latest = get()
      if (latest.activeScopeKey === scopeKey && latest.requestEpoch === epoch) {
        set({ phase: previousPhase, error: getWorkbenchErrorMessage(error) })
      }
      throw error
    }
  },

  confirmSwitch: async (decision) => {
    const pending = get().pendingSwitch
    if (!pending) return
    await get().selectProject(pending.toProjectId, decision)
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
