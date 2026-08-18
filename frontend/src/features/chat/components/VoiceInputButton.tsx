/**
 * 语音输入按钮组件
 * 使用 MediaRecorder API 采集音频，点击切换录音状态。
 * 桌面端通过 Electron IPC 请求麦克风权限，Web 端使用浏览器原生 API。
 * 录音时显示波形动画（CSS animation 模拟）。
 */
import { useState, useRef, useCallback, useEffect } from 'react'
import { Mic, MicOff } from 'lucide-react'
import { appLogger } from '@/shared/utils/logger'
import { voiceApi } from '@/shared/api/voiceApi'
import { isDesktop, getDesktopApi } from '@/shared/utils/platform'
import styles from './VoiceInputButton.module.css'

interface VoiceInputButtonProps {
  /** 录音完成后回调，传入识别文本 */
  onTranscriptionResult: (text: string) => void
  /** 是否禁用语音输入 */
  disabled?: boolean
}

/**
 * 通过桌面端 IPC 请求麦克风权限
 */
async function requestDesktopMicPermission(): Promise<boolean> {
  if (!isDesktop()) return false
  try {
    const desktop = getDesktopApi()
    if (!desktop) return false
    const result = await desktop.ipc.invoke('voice:permission-request') as { granted: boolean }
    return result?.granted === true
  } catch (err) {
    appLogger.warning({ event: 'mic_permission_ipc_error', module: 'voice_input', message: String(err) })
    return false
  }
}

export function VoiceInputButton({ onTranscriptionResult, disabled = false }: VoiceInputButtonProps) {
  const [isRecording, setIsRecording] = useState(false)
  const [permissionError, setPermissionError] = useState<string | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  // 清理资源
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
      }
    }
  }, [])

  /** 开始录音 */
  const startRecording = useCallback(async () => {
    setPermissionError(null)

    // 桌面端：先通过 IPC 请求麦克风权限
    if (isDesktop()) {
      const granted = await requestDesktopMicPermission()
      if (!granted) {
        setPermissionError('麦克风权限请求失败')
        return
      }
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'

      const recorder = new MediaRecorder(stream, { mimeType })

      chunksRef.current = []

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = async () => {
        // 停止所有音轨
        stream.getTracks().forEach((track) => track.stop())

        if (chunksRef.current.length === 0) return

        const audioBlob = new Blob(chunksRef.current, { type: mimeType })
        chunksRef.current = []

        try {
          const result = await voiceApi.sendVoiceForTranscription(audioBlob)
          if (result.text) {
            onTranscriptionResult(result.text)
          }
        } catch (err) {
          appLogger.warning({ event: 'voice_transcribe_error', module: 'voice_input', message: String(err) })
          setPermissionError('语音识别失败，请检查网络连接')
        }
      }

      recorder.onerror = (event: Event) => {
        appLogger.warning({ event: 'media_recorder_error', module: 'voice_input', message: String(event) })
        setIsRecording(false)
        setPermissionError('录音设备出错')
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorderRef.current = recorder
      recorder.start()
      setIsRecording(true)
    } catch (err) {
      const errorMsg = err instanceof DOMException
        ? err.name === 'NotAllowedError'
          ? '麦克风权限被拒绝'
          : err.name === 'NotFoundError'
            ? '未检测到麦克风设备'
            : `录音启动失败: ${err.message}`
        : '录音启动失败'

      appLogger.warning({ event: 'mic_access_error', module: 'voice_input', message: String(err) })
      setPermissionError(errorMsg)
    }
  }, [onTranscriptionResult])

  /** 停止录音 */
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
    }
  }, [])

  /** 点击切换录音状态 */
  const handleToggleRecording = useCallback(() => {
    if (disabled) return
    if (isRecording) {
      stopRecording()
    } else {
      void startRecording()
    }
  }, [disabled, isRecording, startRecording, stopRecording])

  return (
    <div className={styles['voice-btn-wrapper']}>
      <button
        className={`${styles['voice-btn']} ${isRecording ? styles['recording'] : ''}`}
        onClick={handleToggleRecording}
        disabled={disabled}
        title={isRecording ? '停止录音' : '语音输入'}
        aria-label={isRecording ? '停止录音' : '语音输入'}
        data-testid="voice-input-btn"
      >
        {isRecording ? (
          <>
            <MicOff size={18} />
            <span className={styles['wave-animation']}>
              <span className={styles['wave-bar']} />
              <span className={styles['wave-bar']} />
              <span className={styles['wave-bar']} />
              <span className={styles['wave-bar']} />
              <span className={styles['wave-bar']} />
            </span>
          </>
        ) : (
          <Mic size={18} />
        )}
      </button>
      {permissionError && (
        <span className={styles['voice-error']} role="alert">
          {permissionError}
        </span>
      )}
    </div>
  )
}