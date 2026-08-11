import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react'
import { API_BASE_URL } from '@/shared/api/client'
import { useAuthStore } from '@/shared/store/authStore'
import {
  WORKBENCH_CONTEXT_CHANNEL,
  useWorkbenchProjectStore,
} from './store/workbenchProjectStore'
import type { WorkbenchContextBroadcastMessage } from './workbenchTypes'

const WorkbenchScopeContext = createContext<string | null>(null)

function currentUserScopeId(): string | null {
  const state = useAuthStore.getState()
  if (!state.isAuthenticated || !state.user) return null
  return state.user.id ?? state.user.username
}

function buildScopeKey(userId: string): string {
  return `${API_BASE_URL}|${userId}`
}

export function useWorkbenchScopeKey(): string | null {
  return useContext(WorkbenchScopeContext)
}

interface WorkbenchContextProviderProps {
  children: ReactNode
}

export default function WorkbenchContextProvider({
  children,
}: WorkbenchContextProviderProps) {
  const userId = useAuthStore((state) => {
    if (!state.isAuthenticated || !state.user) return null
    return state.user.id ?? state.user.username
  })
  const hydrate = useWorkbenchProjectStore((state) => state.hydrate)
  const resetForServerChange = useWorkbenchProjectStore((state) => state.resetForServerChange)
  const scopeKey = useMemo(() => userId ? buildScopeKey(userId) : null, [userId])

  useEffect(() => {
    if (!scopeKey) {
      resetForServerChange()
      return
    }

    /** hydration 自身已把错误写入 store，此处只结束 effect 的 Promise 链。 */
    const runHydration = (nextScopeKey: string, force = false) => {
      void hydrate(nextScopeKey, force ? { force: true } : undefined).catch(() => undefined)
    }

    runHydration(scopeKey)

    const channel = typeof BroadcastChannel === 'undefined'
      ? null
      : new BroadcastChannel(WORKBENCH_CONTEXT_CHANNEL)

    if (channel) {
      channel.onmessage = (event: MessageEvent<WorkbenchContextBroadcastMessage>) => {
        const message = event.data
        if (message?.type === 'context-changed' && message.scopeKey === scopeKey) {
          runHydration(scopeKey, true)
        }
      }
    }

    const handleFocus = () => {
      const latestUserId = currentUserScopeId()
      if (!latestUserId) {
        resetForServerChange()
        return
      }
      const latestScopeKey = buildScopeKey(latestUserId)
      if (useWorkbenchProjectStore.getState().activeScopeKey !== latestScopeKey) {
        resetForServerChange()
      }
      runHydration(latestScopeKey, true)
    }

    window.addEventListener('focus', handleFocus)
    return () => {
      window.removeEventListener('focus', handleFocus)
      channel?.close()
    }
  }, [hydrate, resetForServerChange, scopeKey])

  return (
    <WorkbenchScopeContext.Provider value={scopeKey}>
      {children}
    </WorkbenchScopeContext.Provider>
  )
}
