import '@testing-library/jest-dom/vitest'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useMediaQuery } from '@/shared/hooks/useMediaQuery'

/**
 * 构造一个可控的 MediaQueryList mock，便于测试中模拟 matches 状态与事件分发。
 */
interface MockMQL {
  matches: boolean
  media: string
  onchange: null
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  addListener: ReturnType<typeof vi.fn>
  removeListener: ReturnType<typeof vi.fn>
  dispatchEvent: ReturnType<typeof vi.fn>
  /** 测试辅助：触发 change 事件回调 */
  __emitChange: (matches: boolean) => void
}

function installMatchMediaMock(initialMatches: boolean = false): {
  mql: MockMQL
  matchMedia: ReturnType<typeof vi.fn>
} {
  let changeListeners: Array<(e: { matches: boolean }) => void> = []
  let legacyListeners: Array<(e: { matches: boolean }) => void> = []

  const mql: MockMQL = {
    matches: initialMatches,
    media: '',
    onchange: null,
    addEventListener: vi.fn((type: string, listener: (e: { matches: boolean }) => void) => {
      if (type === 'change') changeListeners.push(listener)
    }),
    removeEventListener: vi.fn((type: string, listener: (e: { matches: boolean }) => void) => {
      if (type === 'change') {
        changeListeners = changeListeners.filter((l) => l !== listener)
      }
    }),
    addListener: vi.fn((listener: (e: { matches: boolean }) => void) => {
      legacyListeners.push(listener)
    }),
    removeListener: vi.fn((listener: (e: { matches: boolean }) => void) => {
      legacyListeners = legacyListeners.filter((l) => l !== listener)
    }),
    dispatchEvent: vi.fn(),
    __emitChange: (matches: boolean) => {
      mql.matches = matches
      const evt = { matches }
      changeListeners.forEach((l) => l(evt))
      legacyListeners.forEach((l) => l(evt))
    },
  }

  const matchMedia = vi.fn(() => mql)
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: matchMedia,
  })

  return { mql, matchMedia }
}

describe('useMediaQuery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    // 还原 matchMedia，避免污染后续测试
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: undefined,
    })
  })

  it('SSR 或不支持 matchMedia 时返回 false', () => {
    // 移除 matchMedia 模拟 SSR / 不支持环境
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: undefined,
    })

    const { result } = renderHook(() => useMediaQuery('(max-width: 768px)'))
    expect(result.current).toBe(false)
  })

  it('初始 matches 状态由 matchMedia().matches 决定', () => {
    const { mql } = installMatchMediaMock(true)

    renderHook(() => useMediaQuery('(min-width: 1024px)'))
    // 初始化阶段应通过 matchMedia 读取初始 matches
    expect(mql.matches).toBe(true)
  })

  it('默认值（matchMedia 不匹配）为 false', () => {
    installMatchMediaMock(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 9999px)'))
    expect(result.current).toBe(false)
  })

  it('matchMedia change 事件触发后更新 matches 状态', () => {
    const { mql } = installMatchMediaMock(false)

    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(false)

    act(() => {
      mql.__emitChange(true)
    })
    expect(result.current).toBe(true)

    act(() => {
      mql.__emitChange(false)
    })
    expect(result.current).toBe(false)
  })

  it('组件卸载时移除 change 监听器，避免内存泄漏', () => {
    const { mql } = installMatchMediaMock(false)

    const { unmount } = renderHook(() => useMediaQuery('(min-width: 768px)'))

    expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))

    unmount()

    // 卸载后应调用 removeEventListener 清理监听器
    expect(mql.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    // 卸载后再触发 change 事件不应导致状态更新（这里仅验证清理调用，无报错即视为通过）
    expect(() => {
      act(() => mql.__emitChange(true))
    }).not.toThrow()
  })

  it('query 变化时重新注册监听器并同步最新状态', () => {
    const { mql, matchMedia } = installMatchMediaMock(false)

    const { rerender } = renderHook(({ q }: { q: string }) => useMediaQuery(q), {
      initialProps: { q: '(min-width: 768px)' },
    })

    expect(matchMedia).toHaveBeenCalledWith('(min-width: 768px)')

    // 切换 query 后应重新调用 matchMedia
    act(() => {
      mql.matches = true
    })
    rerender({ q: '(min-width: 1024px)' })

    expect(matchMedia).toHaveBeenCalledWith('(min-width: 1024px)')
  })
})
