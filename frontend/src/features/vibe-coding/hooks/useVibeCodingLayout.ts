/**
 * Vibe Coding 小屏布局状态。
 *
 * 终端与文件预览已经迁移到工作台 RuntimeDock，此 Hook 不再保存路径、端口
 * 或终端目录等运行时资源状态。
 */
import { useState } from 'react'

export type VibeCodingPanel = 'sessions' | 'conversation'

export interface UseVibeCodingLayoutReturn {
  activePanel: VibeCodingPanel
  setActivePanel: (panel: VibeCodingPanel) => void
}

export function useVibeCodingLayout(): UseVibeCodingLayoutReturn {
  const [activePanel, setActivePanel] = useState<VibeCodingPanel>('conversation')
  return { activePanel, setActivePanel }
}
