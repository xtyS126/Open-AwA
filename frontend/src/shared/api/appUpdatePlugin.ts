import { registerPlugin } from '@capacitor/core'

/** AppUpdatePlugin 原生能力声明（与 AppUpdatePlugin.java 的 @PluginMethod 一一对应） */
export interface AppUpdateNativePlugin {
  /** 读取本地 APK versionCode / versionName */
  getCurrentVersionCode(): Promise<{ version_code: number; version_name: string }>
  /**
   * 下载 APK 到 cacheDir 并触发系统安装。
   * 无"安装未知应用"权限时 resolve 返回 { code: 'NEED_INSTALL_PERMISSION' }。
   */
  downloadAndInstall(options: {
    url: string
    fileName: string
    sha256: string
    authToken?: string
  }): Promise<{ code?: string; installing?: boolean }>
  /** 订阅下载进度事件（loaded/total/percent） */
  addListener(
    eventName: 'updateProgress',
    listener: (progress: { loaded: number; total: number; percent: number }) => void,
  ): Promise<{ remove: () => void }>
}

export const appUpdatePlugin = registerPlugin<AppUpdateNativePlugin>('AppUpdate')
