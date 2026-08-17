import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { authAPI } from '@/shared/api/authApi'
import { systemAPI } from '@/shared/api/opsApi'
import { getCachedApiKey, isBackendConfigured, refreshCsrfToken } from '@/shared/api/client'
import { isNativeApp } from '@/shared/utils/platform'
import { appLogger } from '@/shared/utils/logger'
import { loadServerPreferences } from '@/shared/utils/preferenceSync'
import { safeGetItem } from '@/shared/utils/safeStorage'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { resetAppInitializationCache } from './appInitializationCache'

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

/**
 * 仅供测试重置模块级初始化缓存，避免跨用例污染。
 */
export function resetAppInitializationStateForTests() {
  resetAppInitializationCache()
}

/**
 * 统一处理应用启动时的 API Key 校验、服务端偏好同步和本地 store 回填。
 *
 * P0 优化：本地状态回填在 hook 调用时同步执行，
 * 确保主题、模型偏好等首屏关键状态在 React 首次渲染前已就位。
 * 网络校验（init-status / auth/me）通过 React Query 管理，StrictMode 双触发时
 * 自动复用在途 Promise，无需手动防重。refreshCsrfToken 等副作用仍由 useEffect
 * 触发，通过 isActive 标志位避免 StrictMode 清理后继续执行。
 */
export function useAppInitialization() {
  const setInitialized = useAuthStore((state) => state.setInitialized)
  const setAuth = useAuthStore((state) => state.setAuth)
  const logout = useAuthStore((state) => state.logout)
  const setSystemInitialized = useAuthStore((state) => state.setSystemInitialized)
  const setNeedsServerSelection = useAuthStore((state) => state.setNeedsServerSelection)
  const needsServerSelection = useAuthStore((state) => state.needsServerSelection)

  // P0: 同步回填本地状态，确保主题等首屏状态在 React 首次渲染前已就位
  // 使用 useState 懒初始化在渲染期间执行一次（StrictMode 下可能多次执行，但 rehydrateStores 幂等）
  useState(() => {
    rehydrateStores()
    return null
  })

  // 步骤 0：APP 模式且未配置后端（或用户主动要求切换服务器）时进入选择流程。
  // 此时默认 /api 指向 WebView 内部不存在的前端路径，发起 init-status
  // 请求只会白等超时，因此必须先让用户选定局域网后端再走后续初始化。
  const isNativeNeedsServerSelection = isNativeApp() && (needsServerSelection || !isBackendConfigured())

  // 步骤 1：检查系统是否已完成首次部署初始化（React Query 自动复用在途 Promise）
  // 未初始化时跳过 API Key 校验，由 RootGuard 跳转到 /setup 引导页
  const { data: initStatusResponse, error: initStatusError } = useQuery({
    queryKey: ['system', 'init-status'],
    queryFn: () => systemAPI.getInitStatus(),
    enabled: !isNativeNeedsServerSelection,
  })

  const initStatusData = initStatusResponse?.data?.data
  const sysInitialized = Boolean(initStatusData?.initialized)
  const hasUsers = initStatusData?.has_users === true

  // 步骤 2：系统已初始化且缓存了 API Key 时校验 API Key（React Query 自动复用在途 Promise）
  const cachedKey = getCachedApiKey()
  const { data: meResponse, error: meError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => authAPI.getMe(),
    enabled: !isNativeNeedsServerSelection && sysInitialized && Boolean(cachedKey),
  })

  useEffect(() => {
    let isActive = true

    const run = async () => {
      // 步骤 0：APP 模式服务器选择
      if (isNativeNeedsServerSelection) {
        setNeedsServerSelection(true)
        setInitialized(true)
        return
      }
      setNeedsServerSelection(false)

      // 步骤 1：等待 init-status 查询完成
      if (initStatusResponse === undefined && !initStatusError) {
        return // 仍在加载
      }

      if (initStatusError) {
        // 不能在无法确认初始化状态时引导用户进入登录或部署流程，避免错误写入。
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'system_init_check',
          status: 'failure',
          message: 'init-status check failed, waiting for a retry',
          extra: { error: initStatusError instanceof Error ? initStatusError.message : String(initStatusError) },
        })
        setSystemInitialized(null)
        setInitialized(true)
        return
      }

      if (!sysInitialized) {
        // 标记文件丢失但数据库已有用户时，直接跳转 /login 而非 /setup，
        // 避免用户在 /setup 提交后被 409 拒绝（PrerequisiteError: 系统已有用户）。
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
          setSystemInitialized(false)
        }
        setInitialized(true)
        return
      }

      setSystemInitialized(true)

      // 步骤 2：无缓存 API Key，直接未认证
      if (!cachedKey) {
        appLogger.info({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'no cached API Key, showing config page',
        })
        logout()
        setInitialized(true)
        return
      }

      // 等待 getMe 查询完成
      if (meResponse === undefined && !meError) {
        return // 仍在加载
      }

      if (meError) {
        const status = (meError as { response?: { status?: number } })?.response?.status
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'API Key validation failed, showing config page',
          extra: { error: meError instanceof Error ? meError.message : String(meError), status_code: status },
        })
        logout()
        setInitialized(true)
        return
      }

      // 认证成功，继续后续流程
      try {
        // 认证状态发布前完成 CSRF 双提交令牌初始化，避免首个 POST 请求先收到 403 再重试。
        await refreshCsrfToken()
        if (!isActive) return

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

        if (!isActive) return

        const data = (meResponse?.data || {}) as {
          username?: string
          nickname?: string | null
          avatar_url?: string | null
          email?: string | null
          phone?: string | null
          role?: string
        }
        setAuth(
          {
            username: data.username || 'admin',
            nickname: data.nickname,
            avatar_url: data.avatar_url,
            email: data.email,
            phone: data.phone,
            role: data.role,
          },
          cachedKey,
        )

        appLogger.info({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'success',
          message: 'API Key validated',
        })

        // 模型选项预加载：复用 GeneralTabContainer.loadGlobalModelOptions 的核心逻辑，
        // 确保首次登录用户进入 /chat 时 selectedModel 已就位，避免发送消息时报错。
        // 性能优化（HAR 抓包证实）：此前在 setInitialized 之前 await 预加载，
        // 导致 modelsApi/billingApi 模块与 3 个 billing XHR 挤占首秒关键路径。
        // 现改为先发布初始化状态（首屏立即渲染），再延迟动态导入并执行预加载；
        // 老用户的 selectedModel 已由 rehydrateStores 从 localStorage 回填，
        // 预加载仅用于校准与补齐首次登录用户的默认模型。
        setInitialized(true)
        window.setTimeout(() => {
          if (!isActive) return
          void import('@/features/chat/utils/preloadModelOptions')
            .then(({ preloadModelOptions }) => preloadModelOptions())
            .catch(() => {
              // preloadModelOptions 内部已 try/catch，此处仅兜底动态导入失败
            })
        }, 1500)
      } catch (error) {
        if (!isActive) return
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'session_validate',
          status: 'failure',
          message: 'initialization failed during post-auth flow',
          extra: { error: error instanceof Error ? error.message : String(error) },
        })
        logout()
        setInitialized(true)
      }
    }

    void run()

    return () => {
      isActive = false
    }
  }, [
    isNativeNeedsServerSelection,
    initStatusResponse,
    initStatusError,
    sysInitialized,
    hasUsers,
    cachedKey,
    meResponse,
    meError,
    logout,
    setAuth,
    setInitialized,
    setNeedsServerSelection,
    setSystemInitialized,
  ])
}
