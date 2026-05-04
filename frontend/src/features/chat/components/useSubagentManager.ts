import { useState, useCallback, useRef } from 'react'

export type SubagentStepType = 'thought' | 'file_read' | 'search' | 'tool_call' | 'generic'

export interface SubagentStep {
  type: SubagentStepType
  label: string
  timestamp: number
}

export interface SubagentTask {
  id: string
  name: string
  status: 'running' | 'completed' | 'error'
  content: string
  exitCode?: number
  completedAt?: number
  steps: SubagentStep[]
}

export function useSubagentManager(onAllCompleted: (aggregatedText: string) => void) {
  const [tasks, setTasks] = useState<SubagentTask[]>([])
  const tasksRef = useRef<SubagentTask[]>([])

  const syncTasks = (newTasks: SubagentTask[]) => {
    let activeTasks = [...newTasks]
    if (activeTasks.length > 20) {
      const completedTasks = activeTasks.filter(t => t.status === 'completed' || t.status === 'error')
      completedTasks.sort((a, b) => (a.completedAt || 0) - (b.completedAt || 0))

      const toRemoveCount = activeTasks.length - 20
      const toRemoveIds = new Set(completedTasks.slice(0, toRemoveCount).map(t => t.id))
      activeTasks = activeTasks.filter(t => !toRemoveIds.has(t.id))
    }

    tasksRef.current = activeTasks
    setTasks(activeTasks)
  }

  const startTask = useCallback((id: string, name: string) => {
    const newTasks = [...tasksRef.current]
    const existingIndex = newTasks.findIndex(t => t.id === id)
    if (existingIndex >= 0) {
      newTasks[existingIndex] = { ...newTasks[existingIndex], status: 'running' }
    } else {
      newTasks.push({ id, name, status: 'running', content: '', steps: [] })
    }
    syncTasks(newTasks)
  }, [])

  const appendLog = useCallback((id: string, log: string) => {
    const newTasks = [...tasksRef.current]
    const existingIndex = newTasks.findIndex(t => t.id === id)
    if (existingIndex >= 0) {
      newTasks[existingIndex] = {
        ...newTasks[existingIndex],
        content: newTasks[existingIndex].content + log + '\n'
      }
      syncTasks(newTasks)
    }
  }, [])

  const appendStep = useCallback((id: string, step: SubagentStep) => {
    const newTasks = [...tasksRef.current]
    const existingIndex = newTasks.findIndex(t => t.id === id)
    if (existingIndex >= 0) {
      newTasks[existingIndex] = {
        ...newTasks[existingIndex],
        steps: [...newTasks[existingIndex].steps, step]
      }
      syncTasks(newTasks)
    }
  }, [])

  const stopTask = useCallback((id: string, status: 'completed' | 'error', exitCode?: number) => {
    const newTasks = [...tasksRef.current]
    const existingIndex = newTasks.findIndex(t => t.id === id)
    if (existingIndex >= 0) {
      newTasks[existingIndex] = {
        ...newTasks[existingIndex],
        status,
        exitCode,
        completedAt: Date.now()
      }
      syncTasks(newTasks)
    }

    const allCompleted = newTasks.every(t => t.status === 'completed' || t.status === 'error')
    if (allCompleted && newTasks.length > 0) {
      const aggregatedText = newTasks.map(t => {
        if (t.status === 'error') {
          return `[ERROR] Subagent ${t.name}: ${t.content}`
        }
        return `[SUCCESS] Subagent ${t.name}:\n${t.content}`
      }).join('\n\n')

      onAllCompleted(aggregatedText)
    }
  }, [onAllCompleted])

  return {
    tasks,
    startTask,
    appendLog,
    appendStep,
    stopTask
  }
}
