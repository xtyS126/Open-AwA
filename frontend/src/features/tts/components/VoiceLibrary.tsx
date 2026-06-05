/**
 * 音色库组件 — 展示预置和复刻音色列表。
 */
import React, { useEffect } from 'react'
import { Mic, Trash2 } from 'lucide-react'
import { useTtsStore } from '../store/ttsStore'
import { ttsApi } from '../ttsApi'
import styles from './VoiceLibrary.module.css'

const VoiceLibrary: React.FC = () => {
  const {
    speakers, selectedSpeakerId, setSelectedSpeaker,
    speakersLoading, loadSpeakers,
  } = useTtsStore()

  useEffect(() => {
    loadSpeakers()
  }, [loadSpeakers])

  const handleDelete = async (e: React.MouseEvent, speakerId: string) => {
    e.stopPropagation()
    if (!confirm(`确定要删除音色 ${speakerId} 吗？`)) return
    try {
      await ttsApi.deleteSpeaker(speakerId)
      loadSpeakers()
    } catch (err) {
      console.error('删除音色失败:', err)
    }
  }

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>音色库</h3>
      {speakersLoading ? (
        <p className={styles.loading}>加载中...</p>
      ) : speakers.length === 0 ? (
        <p className={styles.empty}>暂无可用音色</p>
      ) : (
        <div className={styles.grid}>
          {speakers.map((spk) => (
            <div
              key={spk.speaker_id}
              className={`${styles.card} ${selectedSpeakerId === spk.speaker_id ? styles.selected : ''}`}
              onClick={() => setSelectedSpeaker(spk.speaker_id)}
            >
              <div className={styles.cardHeader}>
                <Mic size={18} className={styles.micIcon} />
                {spk.is_cloned && <span className={styles.clonedBadge}>复刻</span>}
              </div>
              <div className={styles.cardBody}>
                <span className={styles.speakerName}>{spk.name}</span>
                <span className={styles.speakerLang}>{spk.language}</span>
                {spk.description && (
                  <span className={styles.speakerDesc}>{spk.description}</span>
                )}
              </div>
              <div className={styles.cardFooter}>
                <span className={`${styles.statusDot} ${spk.status === 'ready' ? styles.ready : styles.pending}`} />
                <span className={styles.statusText}>{spk.status === 'ready' ? '就绪' : spk.status}</span>
                {spk.is_cloned && (
                  <button
                    className={styles.deleteBtn}
                    onClick={(e) => handleDelete(e, spk.speaker_id)}
                    title="删除此音色"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default React.memo(VoiceLibrary)
