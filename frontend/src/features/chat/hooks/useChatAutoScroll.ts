/**
 * 聊天自动滚动 Hook。
 *
 * 仅在以下条件同时满足时才自动滚动到底部：
 * 1. 用户当前在底部附近（与底部的距离 <= threshold px）
 * 2. 页面可见（非后台标签页）
 * 3. 无用户手动滚动操作正在进行
 *
 * 此外对外暴露：
 * - isNearBottom: 用户是否在底部附近（响应式 state）
 * - hasNewContent: 是否有未读新内容（响应式 state）
 * - scrollToLatest: 强制滚动到底部并重置 hasNewContent（供"跳到最新"按钮使用）
 * - onContentGrow: 流式 chunk 到达或新消息到达时调用，内部判断是否需要自动滚动
 */
import { useRef, useCallback, useEffect, useState } from 'react'

interface AutoScrollOptions {
  /** 判定"在底部附近"的阈值（px），默认 150 */
  threshold?: number
  /** 滚动行为，默认 'auto'（无动画，避免流式时动画堆积） */
  behavior?: ScrollBehavior
}

interface AutoScrollResult {
  /** 绑定到滚动容器的 ref callback */
  containerRef: (el: HTMLElement | null) => void
  /** 执行滚动到底部（受 isNearBottom 节制，force=true 时强制） */
  scrollToBottom: (force?: boolean) => void
  /** 用户是否在底部附近（响应式，UI 可订阅） */
  isNearBottom: boolean
  /** 是否有未读新内容（响应式，UI 可订阅） */
  hasNewContent: boolean
  /** 强制滚动到底部并重置 hasNewContent（供"跳到最新"按钮使用） */
  scrollToLatest: () => void
  /** 流式 chunk 到达或新消息到达时调用，内部判断是否需要自动滚动 */
  onContentGrow: () => void
}

/** 流式期间 onContentGrow 节流间隔（ms），避免动画堆积 */
const CONTENT_GROW_THROTTLE_MS = 200

export function useChatAutoScroll({
  threshold = 150,
  behavior = 'auto',
}: AutoScrollOptions = {}): AutoScrollResult {
  const containerElRef = useRef<HTMLElement | null>(null)
  const handleScrollRef = useRef<(() => void) | null>(null)
  const isNearBottomRef = useRef<boolean>(true)
  const hasNewContentRef = useRef<boolean>(false)
  const userScrollingRef = useRef<boolean>(false)
  const scrollTimerRef = useRef<number | null>(null)
  /** onContentGrow 节流时间戳，避免流式期间高频滚动 */
  const lastGrowScrollRef = useRef<number>(0)

  // 响应式状态：UI 通过这些 state 触发重渲染
  const [isNearBottom, setIsNearBottomState] = useState<boolean>(true)
  const [hasNewContent, setHasNewContentState] = useState<boolean>(false)

  /** 同步 isNearBottom 到 state（避免无变化的冗余 setState） */
  const syncIsNearBottom = useCallback((value: boolean) => {
    if (isNearBottomRef.current !== value) {
      isNearBottomRef.current = value
      setIsNearBottomState(value)
    }
  }, [])

  /** 同步 hasNewContent 到 state（避免无变化的冗余 setState） */
  const syncHasNewContent = useCallback((value: boolean) => {
    if (hasNewContentRef.current !== value) {
      hasNewContentRef.current = value
      setHasNewContentState(value)
    }
  }, [])

  const checkNearBottom = useCallback(() => {
    const el = containerElRef.current
    if (!el) return true
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    return distance <= threshold
  }, [threshold])

  const scrollToBottom = useCallback((force: boolean = false) => {
    if (document.hidden) return
    const el = containerElRef.current
    if (!el) return

    if (!force && !isNearBottomRef.current) return

    // 使用 requestAnimationFrame 确保在 DOM 更新后滚动
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior })
    })
  }, [behavior])

  /**
   * 流式 chunk 到达或新消息到达时调用：
   * - 若用户在底部附近：节流调用 scrollToBottom(false)
   * - 若用户远离底部：设置 hasNewContent=true，提示有未读新内容
   */
  const onContentGrow = useCallback(() => {
    if (isNearBottomRef.current) {
      const now = Date.now()
      if (now - lastGrowScrollRef.current >= CONTENT_GROW_THROTTLE_MS) {
        lastGrowScrollRef.current = now
        scrollToBottom(false)
      }
    } else {
      syncHasNewContent(true)
    }
  }, [scrollToBottom, syncHasNewContent])

  /** 强制滚动到底部并重置 hasNewContent（供"跳到最新"按钮使用） */
  const scrollToLatest = useCallback(() => {
    syncHasNewContent(false)
    // 强制重新判定一次，确保滚动完成后状态正确
    syncIsNearBottom(true)
    scrollToBottom(true)
  }, [scrollToBottom, syncHasNewContent, syncIsNearBottom])

  const containerRef = useCallback((el: HTMLElement | null) => {
    // 清理旧监听器
    if (containerElRef.current && handleScrollRef.current) {
      containerElRef.current.removeEventListener('scroll', handleScrollRef.current)
    }

    if (!el) {
      containerElRef.current = null
      handleScrollRef.current = null
      return
    }

    containerElRef.current = el

    const handleScroll = () => {
      userScrollingRef.current = true
      const nearBottom = checkNearBottom()
      syncIsNearBottom(nearBottom)

      // 用户主动滚动到底部附近时，清除未读新内容标记
      if (nearBottom) {
        syncHasNewContent(false)
      }

      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
      scrollTimerRef.current = window.setTimeout(() => {
        userScrollingRef.current = false
        scrollTimerRef.current = null
      }, 150)
    }

    handleScrollRef.current = handleScroll
    el.addEventListener('scroll', handleScroll, { passive: true })

    // 初始判定
    syncIsNearBottom(checkNearBottom())
  }, [checkNearBottom, syncHasNewContent, syncIsNearBottom])

  useEffect(() => {
    return () => {
      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
    }
  }, [])

  return {
    containerRef,
    scrollToBottom,
    isNearBottom,
    hasNewContent,
    scrollToLatest,
    onContentGrow,
  }
}
