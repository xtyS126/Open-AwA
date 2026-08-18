/**
 * 宠物悬浮窗预加载脚本
 * 通过 contextBridge 暴露白名单 API 给宠物悬浮窗渲染进程
 * 独立于主窗口 preload，仅暴露宠物相关 IPC 通道
 *
 * 安全：sandbox 模式运行，白名单校验，不暴露 ipcRenderer 原始对象
 */
import { contextBridge, ipcRenderer } from 'electron'

/** 允许调用的 IPC 通道白名单（内联字符串，避免 sandbox 下相对路径 require 失败） */
const ALLOWED_INVOKE_CHANNELS = new Set<string>([
  'pet:get-config',
  'pet:set-config',
  'backend:get-url',
  'pet:hide',
])

/** 允许监听的 IPC 通道白名单 */
const ALLOWED_ON_CHANNELS = new Set<string>([
  'pet:play-animation',
  'pet:set-expression',
])

/** 允许发送的 IPC 通道白名单 */
const ALLOWED_SEND_CHANNELS = new Set<string>([
  'pet:clicked',
])

contextBridge.exposeInMainWorld('__OPENAWA_PET_OVERLAY__', {
  /** 获取宠物配置 */
  getConfig: (): Promise<unknown> => {
    return ipcRenderer.invoke('pet:get-config')
  },
  /** 设置宠物配置 */
  setConfig: (config: unknown): Promise<unknown> => {
    return ipcRenderer.invoke('pet:set-config', config)
  },
  /** 监听动画事件（主窗口 -> 悬浮窗转发） */
  onAnimation: (callback: (data: { eventType: string; payload?: Record<string, unknown> }) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: { eventType: string; payload?: Record<string, unknown> }): void => {
      callback(data)
    }
    ipcRenderer.on('pet:play-animation', handler)
    return () => {
      ipcRenderer.removeListener('pet:play-animation', handler)
    }
  },
  /** 监听表情事件（主窗口 -> 悬浮窗转发） */
  onExpression: (callback: (expression: string) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, expression: string): void => {
      callback(expression)
    }
    ipcRenderer.on('pet:set-expression', handler)
    return () => {
      ipcRenderer.removeListener('pet:set-expression', handler)
    }
  },
  /** 通知主窗口：宠物被点击 */
  notifyClicked: (): void => {
    ipcRenderer.send('pet:clicked')
  },
  /** 通用 IPC 调用（白名单校验） */
  ipc: {
    invoke: (channel: string, ...args: unknown[]): Promise<unknown> => {
      if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
        return Promise.reject(new Error(`IPC 通道未授权: ${channel}`))
      }
      return ipcRenderer.invoke(channel, ...args)
    },
    on: (channel: string, listener: (...args: unknown[]) => void): (() => void) => {
      if (!ALLOWED_ON_CHANNELS.has(channel)) {
        throw new Error(`IPC 监听通道未授权: ${channel}`)
      }
      const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]): void => {
        listener(...args)
      }
      ipcRenderer.on(channel, handler)
      return () => {
        ipcRenderer.removeListener(channel, handler)
      }
    },
    send: (channel: string, ...args: unknown[]): void => {
      if (!ALLOWED_SEND_CHANNELS.has(channel)) {
        throw new Error(`IPC 发送通道未授权: ${channel}`)
      }
      ipcRenderer.send(channel, ...args)
    },
  },
})