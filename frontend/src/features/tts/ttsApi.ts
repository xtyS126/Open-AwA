/**
 * 豆包 TTS API 封装。
 * 提供语音合成、声音复刻、音色库等功能的前端 API 调用。
 */
// 直接从 client 导入 axios 实例，避免经由 api.ts barrel 把全部业务 API 模块拉入页面关键路径
import { api, getCachedApiKey } from '@/shared/api/client'

export interface TTSRequest {
  text: string
  speaker_id?: string
  audio_format?: string
  sample_rate?: number
  speed_ratio?: number
  volume_ratio?: number
  pitch_ratio?: number
  emotion?: string | null
  emotion_scale?: number
  context_texts?: string | null
  language?: string
  ssml?: string | null
}

export interface SpeakerInfo {
  speaker_id: string
  name: string
  status: string
  language: string
  is_cloned: boolean
  audio_duration?: number
  created_at?: string
  description?: string
}

export interface CloneStatus {
  success: boolean
  speaker_id: string
  voice_name: string
  status: string
  progress: number
  audio_duration?: number
  created_at?: string
  error_message?: string
}

export interface HealthStatus {
  status: string
  service: string
  configured: boolean
  resource_id: string
  preset_speakers: number
  message: string
}

const API_BASE = '/tts'

export const ttsApi = {
  /** 非流式语音合成，返回 Blob */
  async synthesize(req: TTSRequest): Promise<Blob> {
    const res = await api.post(`${API_BASE}/synthesize`, req, {
      responseType: 'blob',
    })
    return res.data
  },

  /** 流式语音合成（SSE），通过回调接收 base64 音频块 */
  async synthesizeStream(
    req: TTSRequest,
    onChunk: (base64: string) => void,
    onDone: () => void,
    onError: (error: string) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    // SEC-17: token 从内存中的 API Key 缓存读取，不再从 document.cookie 读取
    // 安全考虑：document.cookie 可被 XSS 脚本窃取，内存变量仅运行时存在
    // 优先级：内存变量 > sessionStorage > localStorage（由 client.ts 管理）
    const token = getCachedApiKey() || ''
    const response = await fetch(`/api${API_BASE}/synthesize/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(req),
      credentials: 'include',
      signal,
    })

    if (!response.ok) {
      const errText = await response.text().catch(() => '未知错误')
      onError(`HTTP ${response.status}: ${errText}`)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      onError('无法读取响应流')
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (data === '[DONE]') {
              onDone()
              return
            }
            if (data.startsWith('[ERROR]')) {
              onError(data.slice(8))
              return
            }
            if (data) {
              onChunk(data)
            }
          }
        }
      }
      onDone()
    } catch (e) {
      // AbortError 是用户主动取消，不视为错误
      if (e instanceof DOMException && e.name === 'AbortError') {
        return
      }
      onError(`流读取错误: ${e}`)
    } finally {
      // 确保释放 reader 锁，防止资源泄露
      try {
        reader.releaseLock()
      } catch {
        // reader 已释放或已关闭时忽略
      }
    }
  },

  /** 上传音频创建声音复刻 */
  async cloneVoice(
    voiceName: string,
    audioFile: File,
    contextTexts?: string,
  ): Promise<CloneStatus> {
    const formData = new FormData()
    formData.append('voice_name', voiceName)
    formData.append('audio_file', audioFile)
    if (contextTexts) {
      formData.append('context_texts', contextTexts)
    }
    const res = await api.post(`${API_BASE}/clone`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  },

  /** 查询复刻训练状态 */
  async getCloneStatus(speakerId: string): Promise<CloneStatus> {
    const res = await api.get(`${API_BASE}/clone/${speakerId}`)
    return res.data
  },

  /** 删除复刻音色 */
  async deleteSpeaker(speakerId: string): Promise<void> {
    await api.delete(`${API_BASE}/clone/${speakerId}`)
  },

  /** 获取音色列表 */
  async listSpeakers(): Promise<{ speakers: SpeakerInfo[]; total: number }> {
    const res = await api.get(`${API_BASE}/speakers`)
    return res.data
  },

  /** 健康检查 */
  async health(): Promise<HealthStatus> {
    const res = await api.get(`${API_BASE}/health`)
    return res.data
  },
}
