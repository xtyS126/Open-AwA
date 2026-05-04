import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useSubagentManager } from '@/features/chat/components/useSubagentManager'

describe('useSubagentManager', () => {
  it('should start, append, and stop tasks', () => {
    const onAllCompleted = vi.fn()
    const { result } = renderHook(() => useSubagentManager(onAllCompleted))

    act(() => {
      result.current.startTask('agent-1', 'Agent 1')
    })
    expect(result.current.tasks).toHaveLength(1)
    expect(result.current.tasks[0].status).toBe('running')

    act(() => {
      result.current.appendLog('agent-1', 'Line 1')
    })
    expect(result.current.tasks[0].content).toBe('Line 1\n')

    act(() => {
      result.current.stopTask('agent-1', 'completed')
    })
    expect(result.current.tasks[0].status).toBe('completed')
    expect(onAllCompleted).toHaveBeenCalledWith('[SUCCESS] Subagent Agent 1:\nLine 1\n')
  })

  it('should limit concurrent tasks to 20', () => {
    const onAllCompleted = vi.fn()
    const { result } = renderHook(() => useSubagentManager(onAllCompleted))

    // Add 25 tasks, 5 of them should be removed when more tasks are added
    for (let i = 1; i <= 25; i++) {
      act(() => {
        result.current.startTask(`agent-${i}`, `Agent ${i}`)
      })
      if (i <= 10) {
        act(() => {
          result.current.stopTask(`agent-${i}`, 'completed')
        })
      }
    }

    // It should limit to 20 tasks, removing the oldest completed ones
    expect(result.current.tasks).toHaveLength(20)
    // The first 5 completed tasks should be removed
    expect(result.current.tasks.find(t => t.id === 'agent-1')).toBeUndefined()
    expect(result.current.tasks.find(t => t.id === 'agent-6')).toBeDefined()
  })
})
