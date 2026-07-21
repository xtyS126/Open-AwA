import { useEffect, useRef } from 'react'
import { authAPI, systemAPI } from '@/shared/api/api'
import { getCachedApiKey } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import { loadServerPreferences } from '@/shared/utils/preferenceSync'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { preloadModelOptions } from '@/features/chat/utils/preloadModelOptions'

interface UserProfile {
  username: string
  nickname?: string | null
  avatar_url?: string | null
  email?: string | null
  phone?: string | null
  role?: string
}

interface AppInitializationResult {
  isAuthenticated: boolean
  user?: UserProfile
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
    useModelStore.getState().setSelectedModel(selectedModel, { syncToServer: false })
  }

  const outputMode = safeGetItem('chat_output_mode', '') as 'stream' | 'direct'
  if (outputMode === 'stream' || outputMode === 'direct') {
    usePreferenceStore.getState().setOutputMode(outputMode, { syncToServer: false })
  }

  const thinkingEnabled = safeGetItem('chat_thinking_enabled', '')
  if (thinkingEnabled !== '') {
    usePreferenceStore.getState().setThinkingEnabled(thinkingEnabled === 'true', { syncToServer: false })
  }

  const thinkingDepth = safeGetItem('chat_thinking_depth', '')
  if (thinkingDepth !== '') {
    const parsed = Number(thinkingDepth)
    if (parsed >= 0 && parsed <= 5) {
      usePreferenceStore.getState().setThinkingDepth(parsed, { syncToServer: false })
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

      // 检查是否有缓存的 API Key
      const cachedKey = getCachedApiKey()
      if (!cachedKey) {
        appLogger.info({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'no cached API Key, showing config page',
        })
        cachedInitializationResult = { isAuthenticated: false }
        return cachedInitializationResult
      }

      try {
        // API Key 验证
        let meResponse
        try {
          meResponse = await authAPI.getMe()
        } catch (authError) {
          throw authError
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
          message: 'API Key validated',
        })

        // 模型选项预加载：复用 GeneralTabContainer.loadGlobalModelOptions 的核心逻辑，
        // 确保首次登录用户进入 /chat 时 selectedModel 已就位，避免发送消息时报错。
        // preloadModelOptions 内部已 try/catch 不抛出，await 不会阻塞登录流程。
        // await 确保进入 ChatPage 前 modelOptions 已就绪，避免 ChatPage 渲染时 selectedModel 为空。
        await preloadModelOptions()

        const data = meResponse.data || {}
        cachedInitializationResult = {
          isAuthenticated: true,
          user: {
            username: data.username || 'admin',
            nickname: data.nickname,
            avatar_url: data.avatar_url,
            email: data.email,
            phone: data.phone,
            role: data.role,
          },
        }
        return cachedInitializationResult
      } catch (error) {
        const status = (error as { response?: { status?: number } })?.response?.status
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'API Key validation failed, showing config page',
          extra: { error: error instanceof Error ? error.message : String(error), status_code: status },
        })

        cachedInitializationResult = { isAuthenticated: false }
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
 * 统一处理应用启动时的 API Key 校验、服务端偏好同步和本地 store 回填。
 *
 * P0 优化：本地状态回填在 hook 调用时同步执行，
 * 确保主题、模型偏好等首屏关键状态在 React 首次渲染前已就位。
 * 网络校验（API Key 验证 + 服务端偏好）在后台异步完成。
 */
export function useAppInitialization() {
  const setInitialized = useAuthStore((state) => state.setInitialized)
  const setAuth = useAuthStore((state) => state.setAuth)
  const logout = useAuthStore((state) => state.logout)
  const setSystemInitialized = useAuthStore((state) => state.setSystemInitialized)
  const rehydratedRef = useRef<boolean | null>(null)

  // P0: 同步回填本地状态（仅首次渲染执行，确保主题等首屏状态在 React 首次渲染前已就位）
  // 使用 React 推荐的懒初始化模式：ref.current == null 检查允许在渲染期间访问
  if (rehydratedRef.current == null) {
    rehydratedRef.current = true
    rehydrateStores()
  }

  useEffect(() => {
    let isActive = true

    const initializeApp = async () => {
      // 步骤 1：检查系统是否已完成首次部署初始化
      // 未初始化时跳过 API Key 校验，由 RootGuard 跳转到 /setup 引导页
      try {
        const statusResp = await systemAPI.getInitStatus()
        if (!isActive) return
        const statusData = statusResp.data?.data
        const sysInitialized = !!statusData?.initialized
        setSystemInitialized(sysInitialized)
        if (!sysInitialized) {
          // 标记文件丢失但数据库已有用户时，直接跳转 /login 而非 /setup，
          // 避免用户在 /setup 提交后被 409 拒绝（PrerequisiteError: 系统已有用户）。
          const hasUsers = statusData?.has_users === true
          if (hasUsers) {
            appLogger.info({
              event: 'app_initialize',
              module: 'app',
              action: 'system_init_check',
              status: 'success',
              message: 'system marker missing but DB has users, redirect to /login',
            })
            // 标记系统已初始化，让 RootGuard 走认证流程（/login）
            setSystemInitialized(true)
          } else {
            appLogger.info({
              event: 'app_initialize',
              module: 'app',
              action: 'system_init_check',
              status: 'success',
              message: 'system not initialized, redirect to /setup',
            })
          }
          setInitialized(true)
          return
        }
      } catch (err) {
        if (!isActive) return
        // init-status 接口失败时假定已初始化，走原流程避免阻塞用户
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'system_init_check',
          status: 'failure',
          message: 'init-status check failed, assuming initialized',
          extra: { error: err instanceof Error ? err.message : String(err) },
        })
        setSystemInitialized(true)
      }

      // 步骤 2：系统已初始化，继续原 API Key 校验流程
      const result = await initializeApplicationState()

      if (!isActive) {
        return
      }

      if (result.isAuthenticated && result.user) {
        setAuth(result.user, getCachedApiKey())
      } else {
        logout()
      }

      setInitialized(true)
    }

    void initializeApp()

    return () => {
      isActive = false
    }
  }, [logout, setAuth, setInitialized, setSystemInitialized])
}
