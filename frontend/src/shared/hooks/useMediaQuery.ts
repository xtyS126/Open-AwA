import { useEffect, useState } from 'react'

/**
 * 响应式媒体查询 hook
 *
 * 基于 window.matchMedia API 监听 CSS media query 状态变化，
 * 在组件卸载时自动清理监听器，避免内存泄漏。
 *
 * SSR 安全：在服务端渲染或浏览器不支持 matchMedia 时，统一返回 false，
 * 避免首屏 hydration 不一致。
 *
 * 使用示例：
 *   const isSmallScreen = useMediaQuery('(max-width: 768px)')
 *
 * @param query CSS media query 字符串，如 '(max-width: 768px)'、'(min-width: 1024px)'
 * @returns 当前是否匹配该 query，SSR 或不支持时返回 false
 */
export function useMediaQuery(query: string): boolean {
  // 懒初始化：首屏渲染时同步读取当前 matchMedia 状态，避免首帧闪烁
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return false
    }
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    // SSR 或不支持 matchMedia 的环境直接跳过监听注册
    if (typeof window === 'undefined' || !window.matchMedia) {
      return
    }

    const mql = window.matchMedia(query)
    // 同步当前状态：query 变化后立即与最新值对齐
    setMatches(mql.matches)

    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)

    // 现代浏览器使用 addEventListener；旧版 Safari < 14 仅支持 addListener
    if (mql.addEventListener) {
      mql.addEventListener('change', handler)
      return () => mql.removeEventListener('change', handler)
    } else {
      // 兼容旧版 Safari < 14 的 deprecated API
      mql.addListener(handler)
      return () => mql.removeListener(handler)
    }
  }, [query])

  return matches
}
