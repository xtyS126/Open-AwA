/**
 * TTS 文本转语音组件 — 文本输入 + 参数调节 + 合成 + 播放。
 */
import React, { useCallback } from 'react'
import { Send, Loader2 } from 'lucide-react'
import { useTtsStore } from '../store/ttsStore'
import { ttsApi } from '../ttsApi'
import AudioPlayer from './AudioPlayer'
import styles from './TextToSpeech.module.css'

const EMOTIONS = [
  { value: null, label: '无' },
  { value: 'happy', label: '高兴' },
  { value: 'sad', label: '悲伤' },
  { value: 'angry', label: '愤怒' },
  { value: 'fearful', label: '恐惧' },
  { value: 'surprised', label: '惊讶' },
  { value: 'neutral', label: '中性' },
]

const FORMATS = [
  { value: 'mp3', label: 'MP3' },
  { value: 'wav', label: 'WAV' },
  { value: 'ogg_opus', label: 'OGG' },
]

const TextToSpeech: React.FC = () => {
  const {
    text, setText,
    speedRatio, setSpeedRatio,
    volumeRatio, setVolumeRatio,
    pitchRatio, setPitchRatio,
    emotion, setEmotion,
    emotionScale, setEmotionScale,
    audioFormat, setAudioFormat,
    selectedSpeakerId,
    isSynthesizing, setIsSynthesizing,
    isStreaming, setIsStreaming,
    audioBlob, setAudioBlob,
    audioUrl, setAudioUrl,
  } = useTtsStore()

  const handleSynthesize = useCallback(async () => {
    if (!text.trim() || isSynthesizing) return
    setIsSynthesizing(true)
    setAudioUrl(null)
    setAudioBlob(null)

    try {
      const blob = await ttsApi.synthesize({
        text: text.trim(),
        speaker_id: selectedSpeakerId || undefined,
        audio_format: audioFormat,
        speed_ratio: speedRatio,
        volume_ratio: volumeRatio,
        pitch_ratio: pitchRatio,
        emotion: emotion,
        emotion_scale: emotionScale,
        language: 'zh',
      })
      setAudioBlob(blob)
      const url = URL.createObjectURL(blob)
      setAudioUrl(url)
    } catch (e) {
      console.error('TTS 合成失败:', e)
    } finally {
      setIsSynthesizing(false)
    }
  }, [text, isSynthesizing, selectedSpeakerId, audioFormat, speedRatio, volumeRatio, pitchRatio, emotion, emotionScale, setIsSynthesizing, setAudioUrl, setAudioBlob])

  const handleStreamSynthesize = useCallback(async () => {
    if (!text.trim() || isStreaming) return
    setIsStreaming(true)
    setAudioUrl(null)
    setAudioBlob(null)

    const chunks: string[] = []
    try {
      await ttsApi.synthesizeStream(
        {
          text: text.trim(),
          speaker_id: selectedSpeakerId || undefined,
          audio_format: audioFormat,
          speed_ratio: speedRatio,
          volume_ratio: volumeRatio,
          pitch_ratio: pitchRatio,
          emotion: emotion,
          emotion_scale: emotionScale,
          language: 'zh',
        },
        (base64: string) => {
          chunks.push(base64)
        },
        () => {
          // 流完成 — 合并所有块并创建 Blob
          const binaryStr = atob(chunks.join(''))
          const bytes = new Uint8Array(binaryStr.length)
          for (let i = 0; i < binaryStr.length; i++) {
            bytes[i] = binaryStr.charCodeAt(i)
          }
          const blob = new Blob([bytes], { type: `audio/${audioFormat}` })
          setAudioBlob(blob)
          setAudioUrl(URL.createObjectURL(blob))
          setIsStreaming(false)
        },
        (error: string) => {
          console.error('流式合成失败:', error)
          setIsStreaming(false)
        },
      )
    } catch (e) {
      console.error('流式合成异常:', e)
      setIsStreaming(false)
    }
  }, [text, isStreaming, selectedSpeakerId, audioFormat, speedRatio, volumeRatio, pitchRatio, emotion, emotionScale, setIsStreaming, setAudioUrl, setAudioBlob])

  const isLoading = isSynthesizing || isStreaming

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>文本转语音</h3>

      {/* 文本输入 */}
      <textarea
        className={styles.textarea}
        placeholder="输入要合成的文本..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        maxLength={5000}
      />
      <div className={styles.charCount}>{text.length}/5000</div>

      {/* 参数面板 */}
      <div className={styles.params}>
        <div className={styles.paramRow}>
          <label>语速</label>
          <input
            type="range"
            min={0.5}
            max={2.0}
            step={0.1}
            value={speedRatio}
            onChange={(e) => setSpeedRatio(parseFloat(e.target.value))}
          />
          <span>{speedRatio.toFixed(1)}x</span>
        </div>

        <div className={styles.paramRow}>
          <label>音量</label>
          <input
            type="range"
            min={0.1}
            max={3.0}
            step={0.1}
            value={volumeRatio}
            onChange={(e) => setVolumeRatio(parseFloat(e.target.value))}
          />
          <span>{volumeRatio.toFixed(1)}x</span>
        </div>

        <div className={styles.paramRow}>
          <label>音调</label>
          <input
            type="range"
            min={-12}
            max={12}
            step={1}
            value={pitchRatio}
            onChange={(e) => setPitchRatio(parseInt(e.target.value))}
          />
          <span>{pitchRatio > 0 ? '+' : ''}{pitchRatio}</span>
        </div>

        <div className={styles.paramRow}>
          <label>情感</label>
          <select
            value={emotion || ''}
            onChange={(e) => setEmotion(e.target.value || null)}
          >
            {EMOTIONS.map((em) => (
              <option key={em.value || 'none'} value={em.value || ''}>{em.label}</option>
            ))}
          </select>
          {emotion && (
            <>
              <label>强度</label>
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={emotionScale}
                onChange={(e) => setEmotionScale(parseInt(e.target.value))}
              />
              <span>{emotionScale}</span>
            </>
          )}
        </div>

        <div className={styles.paramRow}>
          <label>格式</label>
          <select
            value={audioFormat}
            onChange={(e) => setAudioFormat(e.target.value)}
          >
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* 合成按钮 */}
      <div className={styles.actions}>
        <button
          className={styles.synthBtn}
          onClick={handleSynthesize}
          disabled={isLoading || !text.trim()}
        >
          {isSynthesizing ? <Loader2 size={16} className={styles.spin} /> : <Send size={16} />}
          <span>合成</span>
        </button>
        <button
          className={styles.streamBtn}
          onClick={handleStreamSynthesize}
          disabled={isLoading || !text.trim()}
        >
          {isStreaming ? <Loader2 size={16} className={styles.spin} /> : <Send size={16} />}
          <span>流式合成</span>
        </button>
      </div>

      {/* 音频播放器 */}
      {(audioUrl || audioBlob) && (
        <AudioPlayer
          audioUrl={audioUrl}
          audioBlob={audioBlob}
          audioFormat={audioFormat}
        />
      )}
    </div>
  )
}

export default React.memo(TextToSpeech)
