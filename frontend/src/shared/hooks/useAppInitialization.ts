import { useEffect } from 'react'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { loadServerPreferences } from '@/shared/utils/preferenceSync'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { useChatStore } from '@/features/chat/store/chatStore'

interface AppInitializationResult {
  isAuthenticated: boolean
  username?: string
}

let initializationPromise: Promise<AppInitializationResult> | null = null
let cachedInitializationResult: AppInitializationResult | null = null

/**
 * 将本地缓存中的用户偏好回填到各个共享 store，确保首屏渲染与用户历史选择一致。
 */
function rehydrateStores() {
  const theme = safeGetItem('theme', '')
  if (theme === 'dark' || theme === 'light') {
    useThemeStore.getState().setTheme(theme, { syncToServer: false })
  }

  const selectedModel = safeGetItem('chat_selected_model', '')
  if (selectedModel) {
    useChatStore.getState().setSelectedModel(selectedModel, { syncToServer: false })
  }

  const outputMode = safeGetItem('chat_output_mode', '') as 'stream' | 'direct'
  if (outputMode === 'stream' || outputMode === 'direct') {
    useChatStore.getState().setOutputMode(outputMode, { syncToServer: false })
  }

  const thinkingEnabled = safeGetItem('chat_thinking_enabled', '')
  if (thinkingEnabled !== '') {
    useChatStore.getState().setThinkingEnabled(thinkingEnabled === 'true', { syncToServer: false })
  }

  const thinkingDepth = safeGetItem('chat_thinking_depth', '')
  if (thinkingDepth !== '') {
    const parsed = Number(thinkingDepth)
    if (parsed >= 0 && parsed <= 5) {
      useChatStore.getState().setThinkingDepth(parsed, { syncToServer: false })
    }
  }
}

async function initializeApplicationState(): Promise<AppInitializationResult> {
  if (cachedInitializationResult) {
    return cachedInitializationResult
  }

  if (!initializationPromise) {
    initializationPromise = (async () => {
      appLogger.info({
        event: 'app_initialize',
        module: 'app',
        action: 'initialize',
        status: 'start',
        message: 'app initialization started',
      })

      try {
        // P1 fix: auth 校验与偏好同步分离，偏好失败不影响登录态
        let meResponse
        try {
          meResponse = await authAPI.getMe()
        } catch (authError) {
          throw authError  // auth 失败直接抛到外层 catch 处理
        }

        // 偏好同步独立执行，失败不阻断登录
        try {
          await loadServerPreferences()
        } catch (prefError) {
          appLogger.warning({
            event: 'app_initialize',
            module: 'app',
            action: 'preference_sync',
            status: 'failure',
            message: 'server preference sync failed, using local defaults',
            extra: { error: prefError instanceof Error ? prefError.message : String(prefError) },
          })
        }

        rehydrateStores()

        appLogger.info({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'success',
          message: 'existing session validated',
        })

        cachedInitializationResult = {
          isAuthenticated: true,
          username: meResponse.data?.username || 'user',
        }
        return cachedInitializationResult
      } catch (error) {
        const status = (error as { response?: { status?: number } })?.response?.status
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'session validation failed, redirecting to login',
          extra: { error: error instanceof Error ? error.message : String(error), status_code: status },
        })

        cachedInitializationResult = {
          isAuthenticated: false,
        }
        return cachedInitializationResult
      } finally {
        initializationPromise = null
      }
    })()
  }

  return initializationPromise
}

/**
 * 仅供测试重置模块级初始化缓存，避免跨用例污染。
 */
export function resetAppInitializationStateForTests() {
  initializationPromise = null
  cachedInitializationResult = null
}

/**
 * 统一处理应用启动时的会话校验、服务端偏好同步和本地 store 回填。
 *
 * P0 优化：本地状态回填在 hook 调用时同步执行，
 * 确保主题、模型偏好等首屏关键状态在 React 首次渲染前已就位。
 * 网络校验（会话验证 + 服务端偏好）在后台异步完成。
 */
export function useAppInitialization() {
  const setInitialized = useAuthStore((state) => state.setInitialized)
  const setAuth = useAuthStore((state) => state.setAuth)
  const logout = useAuthStore((state) => state.logout)

  // P0: 同步回填本地状态，不等待网络请求
  rehydrateStores()

  useEffect(() => {
    let isActive = true

    const initializeApp = async () => {
      const result = await initializeApplicationState()

      if (!isActive) {
        return
      }

      if (result.isAuthenticated) {
        setAuth({ username: result.username || 'user' }, null)
      } else {
        logout()
      }

      setInitialized(true)
    }

    void initializeApp()

    return () => {
      isActive = false
    }
  }, [logout, setAuth, setInitialized])
}