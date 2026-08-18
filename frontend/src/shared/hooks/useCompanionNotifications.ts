/**
 * 陪伴通知 Hook
 * 定时轮询后端陪伴事件检查 API，有事件时通过桌面端 IPC 或浏览器 Notification API 发送通知。
 * 监听通知点击事件，导航到对应页面。
 */
import { useEffect, useRef, useCallback } from 'react'
import { useNavigate, type NavigateFunction } from '@/shared/routing'
import { isDesktop, getDesktopApi } from '@/shared/utils/platform'

/** 陪伴事件类型 */
type CompanionEventType = 'bond_upgrade' | 'milestone' | 'diary_ready' | 'inactivity_reminder'

/** 陪伴事件条目 */
interface CompanionEventItem {
  type: CompanionEventType
  title: string
  body: string
  navigate_to?: string
}

/** 陪伴事件检查响应 */
interface CompanionCheckEventsResponse {
  success: boolean
  events: CompanionEventItem[]
  checked_at: string
}

/** 默认轮询间隔（毫秒）：5 分钟 */
const DEFAULT_POLL_INTERVAL = 5 * 60 * 1000

/** 已通知事件缓存（按 type+title 去重），防止重复通知 */
const notifiedCache = new Set<string>()

/**
 * 通过桌面端 IPC 发送原生通知
 */
async function sendDesktopNotification(item: CompanionEventItem): Promise<void> {
  const desktopApi = getDesktopApi()
  if (!desktopApi) return

  try {
    await desktopApi.ipc.invoke('companion:notify', {
      type: item.type,
      title: item.title,
      body: item.body,
      navigateTo: item.navigate_to,
    })
  } catch {
    // 桌面端通知发送失败时静默处理，不阻塞事件循环
  }
}

/**
 * 通过浏览器 Notification API 发送 Web 通知
 */
function sendWebNotification(item: CompanionEventItem): void {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
    return
  }

  const notification = new Notification(item.title, {
    body: item.body,
    requireInteraction: false,
  })

  notification.onclick = () => {
    window.focus()
    if (item.navigate_to) {
      // 通过自定义事件传递导航路径，由调用方处理路由跳转
      window.dispatchEvent(
        new CustomEvent('companion:notification-clicked', {
          detail: { navigateTo: item.navigate_to },
        })
      )
    }
  }
}

/**
 * 请求浏览器通知权限（Web 环境）
 */
async function requestWebNotificationPermission(): Promise<void> {
  if (typeof Notification === 'undefined') return

  if (Notification.permission === 'default') {
    try {
      await Notification.requestPermission()
    } catch {
      // 权限请求失败时静默处理
    }
  }
}

/**
 * 陪伴通知自定义 Hook
 *
 * 桌面端：定时调用后端 check-events API，有事件时通过 IPC 发送原生通知，
 *         监听 companion:notify-clicked 事件进行路由导航。
 * Web 端：使用浏览器 Notification API，监听自定义事件进行导航。
 *
 * @param backendUrl - 后端 API 基础 URL
 * @param pollInterval - 轮询间隔（毫秒），默认 5 分钟
 * @param enabled - 是否启用通知检查，默认 true
 */
export function useCompanionNotifications(
  backendUrl: string,
  pollInterval: number = DEFAULT_POLL_INTERVAL,
  enabled: boolean = true,
): void {
  const navigate: NavigateFunction = useNavigate()
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const navigateRef = useRef<NavigateFunction>(navigate)

  // 保持 navigate 引用最新
  useEffect(() => {
    navigateRef.current = navigate
  }, [navigate])

  /**
   * 轮询后端陪伴事件检查 API
   */
  const pollEvents = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/companion/check-events`, {
        credentials: 'include',
      })

      if (!response.ok) return

      const data: CompanionCheckEventsResponse = await response.json()

      if (!data.success || data.events.length === 0) return

      // 处理每个事件，去重后发送通知
      for (const item of data.events) {
        const cacheKey = `${item.type}_${item.title}`
        if (notifiedCache.has(cacheKey)) continue
        notifiedCache.add(cacheKey)

        if (isDesktop()) {
          await sendDesktopNotification(item)
        } else {
          sendWebNotification(item)
        }
      }
    } catch {
      // 轮询失败静默处理，不影响用户体验
    }
  }, [backendUrl])

  // 初始化：Web 环境请求通知权限
  useEffect(() => {
    if (!isDesktop()) {
      requestWebNotificationPermission()
    }
  }, [])

  // 监听桌面端通知点击事件
  useEffect(() => {
    if (!isDesktop()) return

    const desktopApi = getDesktopApi()
    if (!desktopApi) return

    const unsubscribe = desktopApi.ipc.on(
      'companion:notify-clicked',
      (payload: unknown) => {
        const data = payload as { navigateTo?: string } | undefined
        if (data?.navigateTo) {
          void navigateRef.current(data.navigateTo)
        }
      }
    )

    return () => {
      unsubscribe()
    }
  }, [])

  // 监听 Web 端通知点击事件
  useEffect(() => {
    if (isDesktop()) return

    const handler = (event: Event) => {
      const customEvent = event as CustomEvent<{ navigateTo?: string }>
      if (customEvent.detail?.navigateTo) {
        void navigateRef.current(customEvent.detail.navigateTo)
      }
    }

    window.addEventListener('companion:notification-clicked', handler)
    return () => {
      window.removeEventListener('companion:notification-clicked', handler)
    }
  }, [])

  // 定时轮询
  useEffect(() => {
    if (!enabled) return

    // 立即执行一次检查
    pollEvents()

    pollTimerRef.current = setInterval(pollEvents, pollInterval)

    return () => {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [enabled, pollInterval, pollEvents])
}