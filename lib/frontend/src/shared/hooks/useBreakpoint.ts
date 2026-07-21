import { useMediaQuery } from './useMediaQuery'

/** 响应式断点标识，与 tokens.css 中 --breakpoint-xs/sm/md/lg/xl 一一对应 */
export type Breakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

/** useBreakpoint 返回的断点状态 */
export interface BreakpointState {
  /** 当前命中的断点标识 */
  breakpoint: Breakpoint
  /** 是否为移动端（≤ md，即视口宽度 < 768px） */
  isMobile: boolean
  /** 是否为平板（md ~ lg，即视口宽度 768~1023px） */
  isTablet: boolean
  /** 是否为桌面端（≥ lg，即视口宽度 ≥ 1024px） */
  isDesktop: boolean
}

/**
 * 响应式断点 hook
 *
 * 与 tokens.css 中的 --breakpoint-xs/sm/md/lg/xl 令牌保持一致：
 * - xs: < 480px
 * - sm: 480px ~ 639px
 * - md: 640px ~ 767px
 * - lg: 768px ~ 1023px
 * - xl: ≥ 1024px
 *
 * 注：本实现采用 min-width + max-width 区间互斥判断，确保同一时刻仅命中一个断点，
 * 避免下游组件出现"sm 和 md 同时为 true"的歧义状态。
 *
 * 派生布尔值的定义（与项目"≤ 768px 为移动端"约定对齐）：
 * - isMobile: 断点 ∈ { xs, sm, md }（视口 < 768px）
 * - isTablet: 断点 === lg（视口 768~1023px）
 * - isDesktop: 断点 === xl（视口 ≥ 1024px）
 *
 * @returns 当前断点标识及派生布尔值
 */
export function useBreakpoint(): BreakpointState {
  // 通过区间互斥的 media query 命中唯一断点，避免多 query 同时匹配
  const isXl = useMediaQuery('(min-width: 1024px)')
  const isLg = useMediaQuery('(min-width: 768px) and (max-width: 1023.98px)')
  const isMd = useMediaQuery('(min-width: 640px) and (max-width: 767.98px)')
  const isSm = useMediaQuery('(min-width: 480px) and (max-width: 639.98px)')
  // xs: < 480px，未命中以上任何 query 即视为 xs

  let breakpoint: Breakpoint = 'xs'
  if (isXl) breakpoint = 'xl'
  else if (isLg) breakpoint = 'lg'
  else if (isMd) breakpoint = 'md'
  else if (isSm) breakpoint = 'sm'

  // 派生布尔值：以"≤ 768px 视为移动端"的项目约定为基准
  const isMobile = breakpoint === 'xs' || breakpoint === 'sm' || breakpoint === 'md'
  const isTablet = breakpoint === 'lg'
  const isDesktop = breakpoint === 'xl'

  return { breakpoint, isMobile, isTablet, isDesktop }
}
