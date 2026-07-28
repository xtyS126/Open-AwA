/**
 * Vibe Coding 三栏布局状态 hook。
 *
 * 抽离 VibeCodingPage 中与布局相关的状态与工具函数：
 *   1. 中栏面板切换（ACP 会话面板 / 终端面板）
 *   2. 移动端 Tab 切换（会话 / 终端 / 预览）
 *   3. 右栏文件预览的选中文件路径与网页预览端口（当前由 FilePreviewPane 内部输入框驱动，
 *      暴露 setter 以便未来接入文件树后编程式设置）
 *   4. resolveTerminalCwd —— 根据当前选中会话解析终端面板使用的工作目录
 *
 * 注意：本 hook 不承载 agents/sessions/notifications 等数据层逻辑，
 * 那些属于数据加载范畴，由 VibeCodingPage 直接管理以保持职责单一。
 */
import { useState } from 'react'
import type { AcpSession } from '@/shared/api/acpApi'

/** 中栏面板类型 —— ACP 会话面板或终端面板 */
export type ActivePane = 'acp' | 'terminal'

/** 移动端 Tab 切换的面板标识：会话 / 终端 / 预览 */
export type MobilePanel = 'session' | 'terminal' | 'preview'

/**
 * 终端面板使用的工作目录：选中会话则用其 cwd，否则回退到当前工作目录。
 * 提取为模块级纯函数，便于单元测试与复用。
 */
export function resolveTerminalCwd(
  sessions: AcpSession[],
  selectedSessionId: string | null,
): string {
  if (selectedSessionId) {
    const matched = sessions.find((s) => s.session_id === selectedSessionId)
    if (matched?.cwd) return matched.cwd
  }
  return '.'
}

export interface UseVibeCodingLayoutReturn {
  /** 中栏当前激活的面板：ACP 会话 / 终端 */
  activePane: ActivePane
  /** 切换中栏面板 */
  setActivePane: (pane: ActivePane) => void
  /** 移动端当前激活的 Tab：会话 / 终端 / 预览 */
  activePanel: MobilePanel
  /** 切换移动端 Tab */
  setActivePanel: (panel: MobilePanel) => void
  /** 右栏文件预览：选中的文件路径 */
  selectedFilePath: string | null
  /** 右栏文件预览：网页预览端口 */
  previewPort: number | null
}

/**
 * 管理 Vibe Coding 页面布局相关状态。
 *
 * 默认值：
 *   - activePane: 'acp'（中栏默认显示 ACP 会话面板）
 *   - activePanel: 'terminal'（移动端默认显示终端面板，最常用）
 */
export function useVibeCodingLayout(): UseVibeCodingLayoutReturn {
  // 中栏面板切换：ACP 会话面板 / 终端面板
  const [activePane, setActivePane] = useState<ActivePane>('acp')
  // 移动端 Tab 切换：默认展示终端面板（最常用）
  const [activePanel, setActivePanel] = useState<MobilePanel>('terminal')
  // 右栏文件预览：当前由 FilePreviewPane 内部输入框驱动，
  // 暴露状态以便 VibeCodingPage 传参渲染；setter 暂未在页面层调用，
  // 保留以备未来接入文件树后编程式设置
  const [selectedFilePath, _setSelectedFilePath] = useState<string | null>(null)
  const [previewPort, _setPreviewPort] = useState<number | null>(null)

  return {
    activePane,
    setActivePane,
    activePanel,
    setActivePanel,
    selectedFilePath,
    previewPort,
  }
}
