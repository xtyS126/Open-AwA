import { useEffect, useState } from 'react'

/** useVisualViewport 返回的可视区域状态 */
export interface VisualViewportState {
  /** 当前可视区域高度（px），SSR 或不支持时为 null */
  height: number | null
  /** 当前可视区域宽度（px），SSR 或不支持时为 null */
  width: number | null
  /** 键盘是否弹起：visualViewport.height 显著小于 window.innerHeight（差值 > 100px）时视为弹起 */
  isKeyboardOpen: boolean
  /** 页面顶部偏移（px）：键盘弹起或滚动时通常 > 0 */
  offsetTop: number
}

/**
 * Visual Viewport API hook
 *
 * 用于适配移动端虚拟键盘弹起时的布局调整，区别于 layout viewport，
 * visual viewport 反映用户当前实际可见区域（排除地址栏、虚拟键盘等）。
 *
 * 典型使用场景：
 * - ChatInput 底栏在键盘弹起时自适应可见区域，避免被键盘遮挡
 * - 表单输入框在键盘弹起时滚动到可见位置
 *
 * 键盘弹起判定逻辑：
 *   isKeyboardOpen = window.innerHeight - visualViewport.height > 100
 * （100px 阈值用于过滤地址栏伸缩等小幅度变化，仅识别明显的键盘占用）
 *
 * 兼容性：iOS Safari 13+, Chrome 61+, Firefox 91+
 * SSR 或不支持 window.visualViewport 的环境返回 null 状态与 isKeyboardOpen=false。
 *
 * @returns 当前可视区域的尺寸、偏移与键盘弹起状态
 */
export function useVisualViewport(): VisualViewportState {
  // 懒初始化：首屏同步读取当前 visualViewport 状态
  const [state, setState] = useState<VisualViewportState>(() => {
    if (typeof window === 'undefined' || !window.visualViewport) {
      return { height: null, width: null, isKeyboardOpen: false, offsetTop: 0 }
    }
    const vv = window.visualViewport
    return {
      height: vv.height,
      width: vv.width,
      isKeyboardOpen: window.innerHeight - vv.height > 100,
      offsetTop: vv.offsetTop,
    }
  })

  useEffect(() => {
    // SSR 或不支持 visualViewport 的环境直接跳过监听注册
    if (typeof window === 'undefined' || !window.visualViewport) {
      return
    }

    const vv = window.visualViewport

    const handler = () => {
      setState({
        height: vv.height,
        width: vv.width,
        isKeyboardOpen: window.innerHeight - vv.height > 100,
        offsetTop: vv.offsetTop,
      })
    }

    // resize 事件反映尺寸变化（键盘弹起/收起），scroll 事件反映偏移变化
    vv.addEventListener('resize', handler)
    vv.addEventListener('scroll', handler)

    return () => {
      vv.removeEventListener('resize', handler)
      vv.removeEventListener('scroll', handler)
    }
  }, [])

  return state
}
