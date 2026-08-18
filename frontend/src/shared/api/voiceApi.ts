/**
 * 语音 API 模块。
 * 封装语音转文本（ASR）相关的前端 API 调用。
 */
import { api } from './client'

export interface TranscribeResponse {
  text: string
  language?: string
  duration?: number
}

const API_BASE = '/voice'

export const voiceApi = {
  /**
   * 发送音频进行语音识别
   * @param audioBlob 音频 Blob（audio/webm 格式）
   * @returns 识别结果文本
   */
  async sendVoiceForTranscription(audioBlob: Blob): Promise<TranscribeResponse> {
    const formData = new FormData()
    formData.append('audio_file', audioBlob, 'recording.webm')

    const res = await api.post(`${API_BASE}/transcribe`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30000, // 30 秒超时，音频文件可能较大
    })
    return res.data
  },
}