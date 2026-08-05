/**
 * 运行平台工具：区分浏览器 Web 与 Capacitor 原生容器（Android/iOS）。
 *
 * APP 模式下需要的行为差异：
 * - API Key 持久化到 localStorage（WebView 进程可被系统回收，sessionStorage 会丢失）
 * - 启动时若未配置后端，直接进入服务器选择页，不发起无效的 /api 探测
 */
import { Capacitor } from '@capacitor/core'

/** 是否运行在 Capacitor 原生容器内（非浏览器） */
export const isNativeApp = (): boolean => {
  try {
    return Capacitor.isNativePlatform()
  } catch {
    return false
  }
}

/**
 * 原生容器内移除 Google Fonts 引用（main.tsx 启动时调用一次）。
 *
 * 性能动机：WebView 直连 Google Fonts 在部分网络（如国内）不可达，
 * 异步加载失败会占用 WebView 连接并产生无谓的网络等待；
 * tokens.css 的字体栈已回退到系统字体（Android 为 Roboto），
 * 移除外部字体引用可消除首屏网络依赖。
 */
export function disableExternalFontsInNativeApp(): void {
  if (!isNativeApp()) {
    return
  }
  document
    .querySelectorAll<HTMLLinkElement>(
      'link[href*="fonts.googleapis.com"], link[href*="fonts.gstatic.com"]',
    )
    .forEach((link) => link.remove())
}
