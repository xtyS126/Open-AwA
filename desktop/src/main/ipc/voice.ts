/**
 * 语音相关 IPC 处理器
 * 处理渲染进程的麦克风权限请求、语音录制状态通知和音频数据块接收
 */
import { ipcMain, app, type IpcMainInvokeEvent } from 'electron'
import fs from 'fs'
import path from 'path'
import log from 'electron-log'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import {
  requestMicrophonePermission,
  isMicrophonePermissionGranted,
} from '../voice'

/** 音频数据块内存缓冲区 */
const audioChunkBuffers: Map<string, Buffer[]> = new Map()

/**
 * 处理麦克风权限请求
 * 渲染进程调用此 IPC 请求主进程开启麦克风权限
 */
async function handleVoicePermissionRequest(): Promise<{ granted: boolean }> {
  try {
    requestMicrophonePermission()
    return { granted: true }
  } catch (err) {
    log.error('麦克风权限请求失败:', err)
    return { granted: false }
  }
}

/**
 * 处理渲染进程通知主进程已获得权限
 * 用于确认权限状态同步
 */
async function handleVoiceSetPermission(): Promise<{ granted: boolean }> {
  const granted = isMicrophonePermissionGranted()
  if (!granted) {
    // 若尚未授予，则自动请求
    requestMicrophonePermission()
  }
  return { granted: isMicrophonePermissionGranted() }
}

/**
 * 处理音频数据块接收
 * 将渲染进程传来的音频数据块追加到内存缓冲区中，
 * 当 endOfStream 为 true 时将所有块合并写入临时文件
 */
async function handleVoiceAudioChunk(
  _event: IpcMainInvokeEvent,
  { chunk, endOfStream, sessionId }: { chunk: number[]; endOfStream?: boolean; sessionId?: string }
): Promise<{ filePath?: string; success: boolean }> {
  try {
    const sid = sessionId || 'default'
    const buffer = Buffer.from(chunk)

    if (!audioChunkBuffers.has(sid)) {
      audioChunkBuffers.set(sid, [])
    }
    const chunks = audioChunkBuffers.get(sid)!
    chunks.push(buffer)

    if (endOfStream) {
      // 合并所有音频块
      const combined = Buffer.concat(chunks)
      // 写入临时文件
      const tempDir = app.getPath('temp')
      const fileName = `voice_input_${Date.now()}.webm`
      const filePath = path.join(tempDir, fileName)
      fs.writeFileSync(filePath, combined)
      // 清理缓冲区
      audioChunkBuffers.delete(sid)
      log.info('音频数据已写入临时文件', { filePath, size: combined.length })
      return { filePath, success: true }
    }

    return { success: true }
  } catch (err) {
    log.error('处理音频数据块失败:', err)
    return { success: false }
  }
}

/**
 * 注册语音相关 IPC 处理器
 */
export function registerVoiceIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.VOICE_PERMISSION_REQUEST, handleVoicePermissionRequest)
  ipcMain.handle(IPC_CHANNELS.VOICE_START_LISTENING, handleVoiceSetPermission)
  ipcMain.handle(IPC_CHANNELS.VOICE_STOP_LISTENING, async () => {
    log.info('语音录制已停止')
    return { success: true }
  })
  ipcMain.handle(IPC_CHANNELS.VOICE_AUDIO_CHUNK, handleVoiceAudioChunk)
}