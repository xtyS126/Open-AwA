/**
 * 预加载脚本
 * 通过 contextBridge 暴露白名单 API 给渲染进程
 * 严格隔离：不暴露 ipcRenderer 原始对象
 */
import { contextBridge, ipcRenderer, app } from 'electron'
import { getBackendUrl } from '../shared/config-store'
import { IPC_CHANNELS } from '../shared/ipc-channels'

/** 允许渲染进程调用的 IPC 通道白名单 */
const ALLOWED_INVOKE_CHANNELS = new Set<string>([
  IPC_CHANNELS.BACKEND_GET_URL,
  IPC_CHANNELS.BACKEND_SET_URL,
  IPC_CHANNELS.BACKEND_TEST_CONNECTION,
  IPC_CHANNELS.WINDOW_MINIMIZE,
  IPC_CHANNELS.WINDOW_MAXIMIZE,
  IPC_CHANNELS.WINDOW_CLOSE,
  IPC_CHANNELS.WINDOW_IS_MAXIMIZED,
  IPC_CHANNELS.NOTIFICATION_SHOW,
  IPC_CHANNELS.APP_GET_VERSION,
  IPC_CHANNELS.APP_GET_PLATFORM,
  IPC_CHANNELS.UPDATE_CHECK,
  IPC_CHANNELS.UPDATE_DOWNLOAD,
  IPC_CHANNELS.UPDATE_INSTALL_AND_RESTART,
  IPC_CHANNELS.AUTOSTART_GET,
  IPC_CHANNELS.AUTOSTART_SET,
])

/** 允许渲染进程监听的 IPC 通道白名单 */
const ALLOWED_ON_CHANNELS = new Set<string>([
  IPC_CHANNELS.BACKEND_URL_CHANGED,
  IPC_CHANNELS.NOTIFICATION_CLICKED,
  IPC_CHANNELS.UPDATE_STATUS_CHANGED,
  IPC_CHANNELS.ACTION_NEW_CHAT,
  IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED,
])

/** 后端信息（启动时从 electron-store 读取） */
const backendUrl = getBackendUrl()

/** 应用版本 */
const appVersion = app.getVersion()

// 注入后端信息
contextBridge.exposeInMainWorld('__OPENAWA_BACKEND__', {
  url: backendUrl,
  version: appVersion,
})

// 注入桌面端 API
contextBridge.exposeInMainWorld('__OPENAWA_DESKTOP__', {
  platform: process.platform,
  isPackaged: app.isPackaged,
  ipc: {
    /** 调用主进程 IPC（白名单校验） */
    invoke: (channel: string, ...args: unknown[]): Promise<unknown> => {
      if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
        return Promise.reject(new Error(`IPC 通道未授权: ${channel}`))
      }
      return ipcRenderer.invoke(channel, ...args)
    },
    /** 监听主进程事件（白名单校验） */
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
  },
})
