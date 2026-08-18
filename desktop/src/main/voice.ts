/**
 * 麦克风权限管理模块
 * 通过 Electron session 的权限请求处理器自动授予麦克风权限，
 * 让渲染进程的 MediaRecorder API 可以正常工作。
 * 主进程不直接采集音频，仅管理权限。
 */
import { session } from 'electron'
import log from 'electron-log'

/** 当前是否已授予麦克风权限 */
let microphonePermissionGranted = false

/**
 * 请求麦克风权限
 * 通过 session.defaultSession.setPermissionRequestHandler 自动授予麦克风权限。
 * 调用后，渲染进程再次请求麦克风时会自动通过。
 */
export function requestMicrophonePermission(): void {
  if (microphonePermissionGranted) {
    return
  }

  const ses = session.defaultSession

  ses.setPermissionRequestHandler((_webContents, permission, callback) => {
    if (permission === 'media') {
      // 自动授予媒体权限（包含麦克风）
      callback(true)
      log.info('麦克风权限已自动授予')
    } else {
      callback(false)
    }
  })

  microphonePermissionGranted = true
  log.info('麦克风权限请求处理器已注册')
}

/**
 * 检查当前是否已授予麦克风权限
 */
export function isMicrophonePermissionGranted(): boolean {
  return microphonePermissionGranted
}

/**
 * 重置麦克风权限状态（用于测试或重新初始化）
 */
export function resetMicrophonePermission(): void {
  microphonePermissionGranted = false
  // 清除权限请求处理器，恢复默认行为
  session.defaultSession.setPermissionRequestHandler(null)
  log.info('麦克风权限已重置')
}