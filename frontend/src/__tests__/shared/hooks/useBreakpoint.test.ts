import '@testing-library/jest-dom/vitest'
import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'

/**
 * 安装 matchMedia mock，根据 query 自动判断 matches。
 * 实现：根据传入的 media query 字符串解析 min-width / max-width，
 * 并与当前 mock 视口宽度比较，返回 matches 状态。
 */
function installMatchMediaWithViewport(initialWidth: number): {
  setViewportWidth: (width: number) => void
} {
  let currentWidth = initialWidth

  const matchMedia = vi.fn((query: string) => {
    // 解析 min-width 与 max-width（仅支持本 hook 实际使用的语法）
    const minWidthMatch = query.match(/min-width:\s*(\d+(?:\.\d+)?)/)
    const maxWidthMatch = query.match(/max-width:\s*(\d+(?:\.\d+)?)/)
    const minWidth = minWidthMatch ? parseFloat(minWidthMatch[1]) : null
    const maxWidth = maxWidthMatch ? parseFloat(maxWidthMatch[1]) : null

    let matches = true
    if (minWidth !== null) matches = matches && currentWidth >= minWidth
    if (maxWidth !== null) matches = matches && currentWidth <= maxWidth

    const listeners: Array<(e: { matches: boolean }) => void> = []
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn((type: string, listener: (e: { matches: boolean }) => void) => {
        if (type === 'change') listeners.push(listener)
      }),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }
  })

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: matchMedia,
  })

  return {
    setViewportWidth: (width: number) => {
      currentWidth = width
      // 由于 useMediaQuery 在 query 变化时才重新读取 matches，
      // 这里不主动派发事件；测试中通过 rerender 触发状态同步
    },
  }
}

describe('useBreakpoint', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: undefined,
    })
  })

  it('视口 < 480px 时返回 xs 断点', () => {
    installMatchMediaWithViewport(375)
    const { result } = renderHook(() => useBreakpoint())

    expect(result.current.breakpoint).toBe('xs')
    expect(result.current.isMobile).toBe(true)
    expect(result.current.isTablet).toBe(false)
    expect(result.current.isDesktop).toBe(false)
  })

  it('视口 480~639px 时返回 sm 断点', () => {
    installMatchMediaWithViewport(560)
    const { result } = renderHook(() => useBreakpoint())

    expect(result.current.breakpoint).toBe('sm')
    expect(result.current.isMobile).toBe(true)
    expect(result.current.isTablet).toBe(false)
    expect(result.current.isDesktop).toBe(false)
  })

  it('视口 640~767px 时返回 md 断点', () => {
    installMatchMediaWithViewport(720)
    const { result } = renderHook(() => useBreakpoint())

    expect(result.current.breakpoint).toBe('md')
    expect(result.current.isMobile).toBe(true)
    expect(result.current.isTablet).toBe(false)
    expect(result.current.isDesktop).toBe(false)
  })

  it('视口 768~1023px 时返回 lg 断点（平板）', () => {
    installMatchMediaWithViewport(900)
    const { result } = renderHook(() => useBreakpoint())

    expect(result.current.breakpoint).toBe('lg')
    expect(result.current.isMobile).toBe(false)
    expect(result.current.isTablet).toBe(true)
    expect(result.current.isDesktop).toBe(false)
  })

  it('视口 ≥ 1024px 时返回 xl 断点（桌面端）', () => {
    installMatchMediaWithViewport(1440)
    const { result } = renderHook(() => useBreakpoint())

    expect(result.current.breakpoint).toBe('xl')
    expect(result.current.isMobile).toBe(false)
    expect(result.current.isTablet).toBe(false)
    expect(result.current.isDesktop).toBe(true)
  })

  it('断点边界值：480/640/768/1024 命中正确断点', () => {
    // 480 应进入 sm 区间
    installMatchMediaWithViewport(480)
    expect(renderHook(() => useBreakpoint()).result.current.breakpoint).toBe('sm')

    // 640 应进入 md 区间
    installMatchMediaWithViewport(640)
    expect(renderHook(() => useBreakpoint()).result.current.breakpoint).toBe('md')

    // 768 应进入 lg 区间
    installMatchMediaWithViewport(768)
    expect(renderHook(() => useBreakpoint()).result.current.breakpoint).toBe('lg')

    // 1024 应进入 xl 区间
    installMatchMediaWithViewport(1024)
    expect(renderHook(() => useBreakpoint()).result.current.breakpoint).toBe('xl')
  })

  it('isMobile/isTablet/isDesktop 派生布尔值互斥正确', () => {
    // 移动端示例：375px
    installMatchMediaWithViewport(375)
    const mobileResult = renderHook(() => useBreakpoint()).result.current
    expect(mobileResult.isMobile).toBe(true)
    expect(mobileResult.isTablet).toBe(false)
    expect(mobileResult.isDesktop).toBe(false)

    // 平板示例：900px
    installMatchMediaWithViewport(900)
    const tabletResult = renderHook(() => useBreakpoint()).result.current
    expect(tabletResult.isMobile).toBe(false)
    expect(tabletResult.isTablet).toBe(true)
    expect(tabletResult.isDesktop).toBe(false)

    // 桌面示例：1920px
    installMatchMediaWithViewport(1920)
    const desktopResult = renderHook(() => useBreakpoint()).result.current
    expect(desktopResult.isMobile).toBe(false)
    expect(desktopResult.isTablet).toBe(false)
    expect(desktopResult.isDesktop).toBe(true)
  })
})
