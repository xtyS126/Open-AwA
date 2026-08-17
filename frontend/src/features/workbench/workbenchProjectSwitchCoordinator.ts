import type {
  WorkbenchPendingSwitch,
  WorkbenchProjectId,
  WorkbenchProjectSwitchBlocker,
} from './workbenchTypes'

export interface WorkbenchProjectSwitchParticipant {
  id: string
  preflight: (request: Omit<WorkbenchPendingSwitch, 'blockers'>) => WorkbenchProjectSwitchBlocker[]
  syncCommittedProject?: (
    projectId: WorkbenchProjectId | null,
    generation: number,
  ) => void
  prepareSwitch?: (
    request: Omit<WorkbenchPendingSwitch, 'blockers'>,
    decision?: WorkbenchProjectSwitchDecision,
  ) => Promise<WorkbenchPreparedProjectSwitch>
}

export type WorkbenchProjectSwitchDecision = 'save' | 'discard'

export interface WorkbenchPreparedProjectSwitch {
  commit: (generation: number) => void | Promise<void>
  abort?: () => void | Promise<void>
}

const participants = new Map<string, WorkbenchProjectSwitchParticipant>()

export function registerWorkbenchProjectSwitchParticipant(
  participant: WorkbenchProjectSwitchParticipant,
): () => void {
  participants.set(participant.id, participant)
  return () => {
    if (participants.get(participant.id) === participant) {
      participants.delete(participant.id)
    }
  }
}

export function collectWorkbenchProjectSwitchBlockers(
  fromProjectId: WorkbenchProjectId | null,
  toProjectId: WorkbenchProjectId,
): WorkbenchProjectSwitchBlocker[] {
  const request = { fromProjectId, toProjectId }
  return [...participants.values()].flatMap((participant) => participant.preflight(request))
}

export async function prepareWorkbenchProjectSwitchParticipants(
  fromProjectId: WorkbenchProjectId | null,
  toProjectId: WorkbenchProjectId,
  decision?: WorkbenchProjectSwitchDecision,
): Promise<WorkbenchPreparedProjectSwitch[]> {
  const request = { fromProjectId, toProjectId }
  const prepared: WorkbenchPreparedProjectSwitch[] = []
  try {
    for (const participant of participants.values()) {
      if (participant.prepareSwitch) {
        prepared.push(await participant.prepareSwitch(request, decision))
      }
    }
    return prepared
  } catch (error) {
    await abortWorkbenchPreparedProjectSwitches(prepared)
    throw error
  }
}

export async function commitWorkbenchPreparedProjectSwitches(
  prepared: readonly WorkbenchPreparedProjectSwitch[],
  generation: number,
): Promise<void> {
  for (const item of prepared) {
    await item.commit(generation)
  }
}

export async function abortWorkbenchPreparedProjectSwitches(
  prepared: readonly WorkbenchPreparedProjectSwitch[],
): Promise<void> {
  for (const item of [...prepared].reverse()) {
    await item.abort?.()
  }
}

export function syncWorkbenchCommittedProject(
  projectId: WorkbenchProjectId | null,
  generation: number,
): void {
  for (const participant of participants.values()) {
    participant.syncCommittedProject?.(projectId, generation)
  }
}
