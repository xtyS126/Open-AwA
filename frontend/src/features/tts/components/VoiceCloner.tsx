/**
 * 声音复刻组件 — 上传音频样本，创建专属音色。
 */
import React, { useState, useCallback, useRef } from 'react'
import { Upload, Loader2, CheckCircle, XCircle } from 'lucide-react'
import { ttsApi } from '../ttsApi'
import { useTtsStore } from '../store/ttsStore'
import styles from './VoiceCloner.module.css'

const VoiceCloner: React.FC = () => {
  const {
    cloneProgress, cloneStatus, cloneSpeakerId, cloneError,
    setCloneProgress, setCloneStatus, setCloneSpeakerId, setCloneError,
    resetCloneState, loadSpeakers,
  } = useTtsStore()

  const [voiceName, setVoiceName] = useState('')
  const [contextTexts, setContextTexts] = useState('')
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.name.toLowerCase().endsWith('.wav')) {
      alert('仅支持 WAV 格式音频文件')
      return
    }
    if (file.size < 1024) {
      alert('音频文件过小，需要至少 14 秒的录音')
      return
    }
    setAudioFile(file)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && file.name.toLowerCase().endsWith('.wav')) {
      setAudioFile(file)
    }
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!voiceName.trim() || !audioFile || isSubmitting) return

    setIsSubmitting(true)
    setCloneError(null)
    setCloneStatus('uploading')

    try {
      const result = await ttsApi.cloneVoice(
        voiceName.trim(),
        audioFile,
        contextTexts.trim() || undefined,
      )
      setCloneSpeakerId(result.speaker_id)
      setCloneStatus('training')
      setCloneProgress(10)

      // 轮询训练状态
      const pollInterval = setInterval(async () => {
        try {
          const status = await ttsApi.getCloneStatus(result.speaker_id)
          if (status.status === 'ready') {
            clearInterval(pollInterval)
            setCloneStatus('ready')
            setCloneProgress(100)
            loadSpeakers()
          } else if (status.status === 'failed') {
            clearInterval(pollInterval)
            setCloneStatus('failed')
            setCloneError(status.error_message || '训练失败')
          } else {
            setCloneProgress(Math.min(cloneProgress + 5, 90))
          }
        } catch {
          // 轮询出错不中断
        }
      }, 3000)
    } catch (e: any) {
      setCloneStatus('failed')
      setCloneError(e?.response?.data?.detail || e?.message || '复刻请求失败')
    } finally {
      setIsSubmitting(false)
    }
  }, [voiceName, audioFile, contextTexts, isSubmitting, cloneProgress, setCloneError, setCloneStatus, setCloneSpeakerId, setCloneProgress, loadSpeakers])

  const handleReset = useCallback(() => {
    resetCloneState()
    setVoiceName('')
    setContextTexts('')
    setAudioFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }, [resetCloneState])

  const isProcessing = cloneStatus === 'uploading' || cloneStatus === 'training' || isSubmitting

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>声音复刻</h3>
      <p className={styles.hint}>
        上传 14~30 秒的 WAV 音频样本，训练专属音色。建议低噪声环境、单人声录音。
      </p>

      {/* 音色名称 */}
      <div className={styles.field}>
        <label>音色名称</label>
        <input
          type="text"
          className={styles.input}
          placeholder="例如：我的声音"
          value={voiceName}
          onChange={(e) => setVoiceName(e.target.value)}
          maxLength={50}
          disabled={isProcessing}
        />
      </div>

      {/* 上下文文本 */}
      <div className={styles.field}>
        <label>音频对应文本（可选，提升训练效果）</label>
        <input
          type="text"
          className={styles.input}
          placeholder="输入音频中说出的文本内容"
          value={contextTexts}
          onChange={(e) => setContextTexts(e.target.value)}
          maxLength={500}
          disabled={isProcessing}
        />
      </div>

      {/* 文件上传区域 */}
      <div
        className={`${styles.dropZone} ${audioFile ? styles.hasFile : ''}`}
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => fileRef.current?.click()}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".wav"
          onChange={handleFileChange}
          className={styles.fileInput}
          disabled={isProcessing}
        />
        {audioFile ? (
          <div className={styles.fileInfo}>
            <Upload size={20} />
            <span>{audioFile.name}</span>
            <span className={styles.fileSize}>{(audioFile.size / 1024).toFixed(1)} KB</span>
          </div>
        ) : (
          <div className={styles.dropPrompt}>
            <Upload size={24} />
            <span>拖拽或点击上传 WAV 文件</span>
            <span className={styles.subHint}>14~30 秒，低噪声单人声</span>
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className={styles.actions}>
        {cloneStatus === 'ready' ? (
          <>
            <div className={styles.successMsg}>
              <CheckCircle size={18} />
              <span>复刻成功！speaker_id: {cloneSpeakerId}</span>
            </div>
            <button className={styles.resetBtn} onClick={handleReset}>重新复刻</button>
          </>
        ) : cloneStatus === 'failed' ? (
          <>
            <div className={styles.errorMsg}>
              <XCircle size={18} />
              <span>{cloneError || '复刻失败'}</span>
            </div>
            <button className={styles.resetBtn} onClick={handleReset}>重试</button>
          </>
        ) : (
          <>
            {/* 进度条 */}
            {isProcessing && (
              <div className={styles.progressWrap}>
                <div className={styles.progressBar}>
                  <div
                    className={styles.progressFill}
                    style={{ width: `${cloneProgress}%` }}
                  />
                </div>
                <span className={styles.progressText}>
                  {cloneStatus === 'uploading' ? '上传中...' : `训练中... ${cloneProgress}%`}
                </span>
              </div>
            )}
            <button
              className={styles.submitBtn}
              onClick={handleSubmit}
              disabled={!voiceName.trim() || !audioFile || isProcessing}
            >
              {isProcessing ? <Loader2 size={16} className={styles.spin} /> : <Upload size={16} />}
              <span>{isProcessing ? '处理中...' : '开始复刻'}</span>
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default React.memo(VoiceCloner)
