/**
 * 桌面端注入的全局对象类型声明
 * Web 端这些对象为 undefined，桌面端由 preload 脚本注入
 */

/** 后端连接信息（桌面端 preload 注入） */
export interface BackendInfo {
  url: string
  version: string
}

/** 桌面端 API（桌面端 preload 注入） */
export interface DesktopApi {
  platform: string
  isPackaged: boolean
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
    on: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}

declare global {
  interface Window {
    /** 桌面端 preload 注入的后端地址 */
    __OPENAWA_BACKEND__?: BackendInfo
    /** 桌面端 preload 注入的原生能力 API */
    __OPENAWA_DESKTOP__?: DesktopApi
  }
}

export {}
