/**
 * 宠物悬浮窗 IPC 处理器
 * 负责处理来自主窗口渲染进程的宠物控制请求，
 * 以及向宠物悬浮窗转发动画/表情事件，接收悬浮窗点击事件回传
 */
import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getPetConfig, setPetConfig } from '../../shared/config-store'
import type { PetConfig } from '../../shared/types'
import {
  getPetOverlay,
  createPetOverlay,
  showPetOverlay,
  hidePetOverlay,
  togglePetOverlay,
  destroyPetOverlay,
} from '../pet-overlay'
import { getMainWindow } from '../window'

/** 处理显示悬浮窗 */
function handleShow(): { success: boolean } {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    showPetOverlay()
    return { success: true }
  }
  // 如果悬浮窗不存在，先创建再显示
  const newWin = createPetOverlay()
  newWin.once('ready-to-show', () => newWin.show())
  return { success: true }
}

/** 处理隐藏悬浮窗 */
function handleHide(): { success: boolean } {
  hidePetOverlay()
  return { success: true }
}

/** 处理切换悬浮窗显示/隐藏 */
function handleToggle(): { success: boolean } {
  togglePetOverlay()
  return { success: true }
}

/** 处理设置悬浮窗位置 */
function handleSetPosition(
  _event: IpcMainInvokeEvent,
  pos: { x: number; y: number }
): { success: boolean } {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    win.setPosition(pos.x, pos.y)
    // 持久化位置
    const config = getPetConfig()
    setPetConfig({ ...config, position: pos })
    log.info('[pet-ipc] 悬浮窗位置已更新', pos)
    return { success: true }
  }
  return { success: false }
}

/** 处理播放动画：主窗口 -> 悬浮窗转发
 * 接收 { eventType, payload } 格式的宠物事件，转发到悬浮窗渲染进程 */
function handlePlayAnimation(
  _event: IpcMainInvokeEvent,
  data: { eventType: string; payload?: Record<string, unknown> }
): { success: boolean } {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    win.webContents.send(IPC_CHANNELS.PET_OVERLAY_PLAY_ANIMATION, data)
    log.info('[pet-ipc] 动画事件已转发到悬浮窗', { eventType: data.eventType })
    return { success: true }
  }
  return { success: false }
}

/** 处理设置表情：主窗口 -> 悬浮窗转发 */
function handleSetExpression(
  _event: IpcMainInvokeEvent,
  expression: string
): { success: boolean } {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    win.webContents.send(IPC_CHANNELS.PET_OVERLAY_SET_EXPRESSION, expression)
    log.info('[pet-ipc] 表情事件已转发到悬浮窗', { expression })
    return { success: true }
  }
  return { success: false }
}

/** 处理获取宠物配置 */
function handleGetConfig(): PetConfig {
  return getPetConfig()
}

/** 处理设置宠物配置 */
function handleSetConfig(
  _event: IpcMainInvokeEvent,
  config: Partial<PetConfig>
): { success: boolean } {
  const current = getPetConfig()
  setPetConfig({ ...current, ...config })
  log.info('[pet-ipc] 宠物配置已更新', config)
  return { success: true }
}

/** 注册宠物悬浮窗 IPC 处理器 */
export function registerPetIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_SHOW, handleShow)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_HIDE, handleHide)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_TOGGLE, handleToggle)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_SET_POSITION, handleSetPosition)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_PLAY_ANIMATION, handlePlayAnimation)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_SET_EXPRESSION, handleSetExpression)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_GET_CONFIG, handleGetConfig)
  ipcMain.handle(IPC_CHANNELS.PET_OVERLAY_SET_CONFIG, handleSetConfig)

  // 宠物悬浮窗点击事件：悬浮窗 -> 主窗口转发
  ipcMain.on(IPC_CHANNELS.PET_OVERLAY_CLICKED, () => {
    const mainWin = getMainWindow()
    if (mainWin && !mainWin.isDestroyed()) {
      if (mainWin.isMinimized()) mainWin.restore()
      mainWin.focus()
      // 转发点击事件到主窗口渲染进程
      mainWin.webContents.send(IPC_CHANNELS.PET_OVERLAY_CLICKED)
    }
    log.info('[pet-ipc] 宠物悬浮窗被点击，已聚焦主窗口')
  })
}