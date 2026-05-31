/**
 * 前端性能指标采集模块。
 * 采集 App Shell 可见时间、路由主要内容可见时间等关键指标。
 */

interface PerfMark {
  name: string
  timestamp: number
}

const marks: PerfMark[] = []

/**
 * 记录一个性能标记点。
 * 在关键渲染节点调用，例如：
 * - app_shell_visible: App Shell 首次渲染完成
 * - auth_resolved: 认证状态解析完成
 * - chat_page_ready: 聊天页主要交互元素就绪
 */
export function mark(name: string): void {
  const timestamp = performance.now()
  marks.push({ name, timestamp })

  if (import.meta.env.DEV) {
    console.debug(`[perf] ${name}: ${timestamp.toFixed(1)}ms`)
  }
}

/**
 * 计算两个标记点之间的耗时。
 * 如果开始标记不存在，返回从页面导航开始到结束标记的耗时。
 */
export function measure(from: string, to: string): number | null {
  const fromMark = marks.find((m) => m.name === from)
  const toMark = marks.find((m) => m.name === to)
  if (!toMark) return null
  const startTime = fromMark?.timestamp ?? 0
  return toMark.timestamp - startTime
}

/**
 * 获取所有已记录的标记点。
 */
export function getAllMarks(): ReadonlyArray<PerfMark> {
  return marks
}

/**
 * 从页面导航开始到当前时刻的耗时（ms）。
 */
export function timeSinceNavigation(): number {
  return performance.now()
}
