/**
 * 音频播放器组件 — HTML5 Audio 封装。
 * 支持播放/暂停、下载、进度条。
 */
import React, { useRef, useEffect, useState, useCallback } from 'react'
import { Play, Pause, Download } from 'lucide-react'
import styles from './AudioPlayer.module.css'

interface AudioPlayerProps {
  audioUrl?: string | null
  audioBlob?: Blob | null
  audioFormat?: string
  onEnded?: () => void
}

const AudioPlayer: React.FC<AudioPlayerProps> = ({
  audioUrl,
  audioBlob,
  audioFormat = 'mp3',
  onEnded,
}) => {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  // 从 Blob 创建本地 URL
  useEffect(() => {
    if (audioBlob) {
      const url = URL.createObjectURL(audioBlob)
      setBlobUrl(url)
      return () => URL.revokeObjectURL(url)
    }
    return undefined
  }, [audioBlob])

  const sourceUrl = audioUrl || blobUrl

  useEffect(() => {
    if (sourceUrl) {
      setIsPlaying(false)
      setCurrentTime(0)
      setDuration(0)
    }
  }, [sourceUrl])

  const handlePlayPause = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !sourceUrl) return
    if (audio.paused) {
      audio.play()
      setIsPlaying(true)
    } else {
      audio.pause()
      setIsPlaying(false)
    }
  }, [sourceUrl])

  const handleTimeUpdate = useCallback(() => {
    const audio = audioRef.current
    if (audio) setCurrentTime(audio.currentTime)
  }, [])

  const handleLoadedMetadata = useCallback(() => {
    const audio = audioRef.current
    if (audio) setDuration(audio.duration)
  }, [])

  const handleSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current
    const time = parseFloat(e.target.value)
    if (audio) {
      audio.currentTime = time
      setCurrentTime(time)
    }
  }, [])

  const handleDownload = useCallback(() => {
    if (!sourceUrl) return
    const a = document.createElement('a')
    a.href = sourceUrl
    a.download = `tts_output.${audioFormat}`
    a.click()
  }, [sourceUrl, audioFormat])

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60)
    const s = Math.floor(t % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  if (!sourceUrl) return null

  return (
    <div className={styles.player}>
      <audio
        ref={audioRef}
        src={sourceUrl}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={() => { setIsPlaying(false); onEnded?.() }}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
      />
      <button className={styles.playBtn} onClick={handlePlayPause} title={isPlaying ? '暂停' : '播放'}>
        {isPlaying ? <Pause size={20} /> : <Play size={20} />}
      </button>
      <div className={styles.progressBar}>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          className={styles.slider}
        />
        <div className={styles.time}>
          <span>{formatTime(currentTime)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>
      <button className={styles.downloadBtn} onClick={handleDownload} title="下载">
        <Download size={16} />
      </button>
    </div>
  )
}

export default React.memo(AudioPlayer)
