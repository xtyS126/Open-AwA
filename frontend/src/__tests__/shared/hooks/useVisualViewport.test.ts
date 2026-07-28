import '@testing-library/jest-dom/vitest'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVisualViewport } from '@/shared/hooks/useVisualViewport'

/**
 * 构造一个可控的 VisualViewport mock，便于测试中模拟尺寸变化与事件分发。
 */
interface MockVisualViewport {
  height: number
  width: number
  offsetTop: number
  offsetLeft: number
  pageTop: number
  scale: number
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  dispatchEvent: ReturnType<typeof vi.fn>
  /** 测试辅助：触发 resize 事件回调 */
  __emitResize: () => void
  /** 测试辅助：触发 scroll 事件回调 */
  __emitScroll: () => void
}

function installVisualViewportMock(initial: {
  height: number
  width: number
  offsetTop?: number
}): { vv: MockVisualViewport } {
  let resizeListeners: Array<() => void> = []
  let scrollListeners: Array<() => void> = []

  const vv: MockVisualViewport = {
    height: initial.height,
    width: initial.width,
    offsetTop: initial.offsetTop ?? 0,
    offsetLeft: 0,
    pageTop: 0,
    scale: 1,
    addEventListener: vi.fn((type: string, listener: () => void) => {
      if (type === 'resize') resizeListeners.push(listener)
      if (type === 'scroll') scrollListeners.push(listener)
    }),
    removeEventListener: vi.fn((type: string, listener: () => void) => {
      if (type === 'resize') resizeListeners = resizeListeners.filter((l) => l !== listener)
      if (type === 'scroll') scrollListeners = scrollListeners.filter((l) => l !== listener)
    }),
    dispatchEvent: vi.fn(),
    __emitResize: () => {
      resizeListeners.forEach((l) => l())
    },
    __emitScroll: () => {
      scrollListeners.forEach((l) => l())
    },
  }

  Object.defineProperty(window, 'visualViewport', {
    writable: true,
    configurable: true,
    value: vv,
  })

  return { vv }
}

describe('useVisualViewport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    // 还原 visualViewport，避免污染后续测试
    Object.defineProperty(window, 'visualViewport', {
      writable: true,
      configurable: true,
      value: undefined,
    })
  })

  it('SSR 或不支持 visualViewport 时返回 null 状态与 isKeyboardOpen=false', () => {
    Object.defineProperty(window, 'visualViewport', {
      writable: true,
      configurable: true,
      value: undefined,
    })

    const { result } = renderHook(() => useVisualViewport())
    expect(result.current.height).toBeNull()
    expect(result.current.width).toBeNull()
    expect(result.current.isKeyboardOpen).toBe(false)
    expect(result.current.offsetTop).toBe(0)
  })

  it('默认值由 visualViewport 初始状态推导', () => {
    // window.innerHeight 在 jsdom 中默认 768
    installVisualViewportMock({ height: 768, width: 1024 })

    const { result } = renderHook(() => useVisualViewport())
    expect(result.current.height).toBe(768)
    expect(result.current.width).toBe(1024)
    // 差值 0，未超过 100px 阈值，键盘视为未弹起
    expect(result.current.isKeyboardOpen).toBe(false)
    expect(result.current.offsetTop).toBe(0)
  })

  it('resize 事件触发后更新 height/width 与键盘状态', () => {
    // 假设浏览器视口高度 800，键盘弹起后 visualViewport.height 收缩到 500
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      writable: true,
      value: 800,
    })

    const { vv } = installVisualViewportMock({ height: 800, width: 400 })
    const { result } = renderHook(() => useVisualViewport())

    expect(result.current.isKeyboardOpen).toBe(false)

    // 模拟键盘弹起：visualViewport 高度收缩到 500（差值 300 > 100）
    act(() => {
      vv.height = 500
      vv.width = 400
      vv.__emitResize()
    })

    expect(result.current.height).toBe(500)
    expect(result.current.width).toBe(400)
    expect(result.current.isKeyboardOpen).toBe(true)

    // 模拟键盘收起：visualViewport 高度恢复到 800
    act(() => {
      vv.height = 800
      vv.__emitResize()
    })

    expect(result.current.height).toBe(800)
    expect(result.current.isKeyboardOpen).toBe(false)
  })

  it('scroll 事件触发后更新 offsetTop', () => {
    const { vv } = installVisualViewportMock({ height: 700, width: 400 })
    const { result } = renderHook(() => useVisualViewport())

    expect(result.current.offsetTop).toBe(0)

    act(() => {
      vv.offsetTop = 120
      vv.__emitScroll()
    })

    expect(result.current.offsetTop).toBe(120)
  })

  it('键盘弹起判定阈值：差值 ≤ 100px 视为未弹起', () => {
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      writable: true,
      value: 800,
    })

    const { vv } = installVisualViewportMock({ height: 750, width: 400 })
    const { result } = renderHook(() => useVisualViewport())

    // 差值 50 < 100，视为未弹起
    expect(result.current.isKeyboardOpen).toBe(false)

    // 差值正好 100，仍未超过阈值
    act(() => {
      vv.height = 700
      vv.__emitResize()
    })
    expect(result.current.isKeyboardOpen).toBe(false)

    // 差值 101 > 100，视为弹起
    act(() => {
      vv.height = 699
      vv.__emitResize()
    })
    expect(result.current.isKeyboardOpen).toBe(true)
  })

  it('组件卸载时移除 resize 与 scroll 监听器', () => {
    const { vv } = installVisualViewportMock({ height: 700, width: 400 })

    const { unmount } = renderHook(() => useVisualViewport())

    expect(vv.addEventListener).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(vv.addEventListener).toHaveBeenCalledWith('scroll', expect.any(Function))

    unmount()

    expect(vv.removeEventListener).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(vv.removeEventListener).toHaveBeenCalledWith('scroll', expect.any(Function))
  })
})
