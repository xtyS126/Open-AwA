/**
 * 聊天自动滚动 Hook。
 *
 * 仅在以下条件同时满足时才自动滚动到底部：
 * 1. 用户当前在底部附近（与底部的距离 <= threshold px）
 * 2. 页面可见（非后台标签页）
 * 3. 无用户手动滚动操作正在进行
 */
import { useRef, useCallback, useEffect } from 'react'

interface AutoScrollOptions {
  /** 判定"在底部附近"的阈值（px），默认 150 */
  threshold?: number
  /** 滚动行为，默认 'auto'（无动画，避免流式时动画堆积） */
  behavior?: ScrollBehavior
}

interface AutoScrollResult {
  /** 绑定到滚动容器的 ref callback */
  containerRef: (el: HTMLElement | null) => void
  /** 执行滚动到底部 */
  scrollToBottom: (force?: boolean) => void
}

export function useChatAutoScroll({
  threshold = 150,
  behavior = 'auto',
}: AutoScrollOptions = {}): AutoScrollResult {
  const containerElRef = useRef<HTMLElement | null>(null)
  const isNearBottomRef = useRef<boolean>(true)
  const userScrollingRef = useRef<boolean>(false)
  const scrollTimerRef = useRef<number | null>(null)

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

  const containerRef = useCallback((el: HTMLElement | null) => {
    if (!el) return
    containerElRef.current = el

    const handleScroll = () => {
      userScrollingRef.current = true
      isNearBottomRef.current = checkNearBottom()

      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
      scrollTimerRef.current = window.setTimeout(() => {
        userScrollingRef.current = false
        scrollTimerRef.current = null
      }, 150)
    }

    el.addEventListener('scroll', handleScroll, { passive: true })

    // 初始判定
    isNearBottomRef.current = checkNearBottom()
  }, [checkNearBottom])

  useEffect(() => {
    return () => {
      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
    }
  }, [])

  return { containerRef, scrollToBottom }
}
