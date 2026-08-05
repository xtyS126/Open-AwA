/**
 * Capacitor 配置：将 Open-AwA Web 前端打包为 Android/iOS 原生应用。
 *
 * 关键决策：
 * - webDir 指向 Vite 构建产物 dist
 * - androidScheme 使用 https（默认），WebView origin 为 https://localhost，
 *   后端 CORS 白名单的正则已放行 localhost，可跨源直连 LAN 后端
 * - allowMixedContent: https 页面直连 http://LAN-IP 的明文后端必须开启，
 *   否则 WebView 拦截所有 http 请求导致无法接入局域网后端
 */
import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.openawa.mobile',
  appName: 'Open-AwA',
  webDir: 'dist',
  android: {
    allowMixedContent: true,
  },
  server: {
    androidScheme: 'https',
  },
}

export default config
