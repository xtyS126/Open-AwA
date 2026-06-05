/**
 * 豆包 TTS 主页面 — 三栏布局。
 * 左侧：音色库 | 中间：TTS 合成 | 右侧：声音复刻
 */
import React from 'react'
import TextToSpeech from './components/TextToSpeech'
import VoiceLibrary from './components/VoiceLibrary'
import VoiceCloner from './components/VoiceCloner'
import styles from './TtsPage.module.css'

const TtsPage: React.FC = () => {
  return (
    <div className={styles.container}>
      {/* 工具栏 */}
      <div className={styles.toolbar}>
        <span className={styles.pageTitle}>豆包 TTS 语音合成</span>
        <span className={styles.subtitle}>
          Doubao-Seed-TTS 2.0 · 声音复刻 2.0
        </span>
      </div>

      {/* 主面板 */}
      <div className={styles.mainPanel}>
        {/* 左侧：音色库 */}
        <div className={styles.leftPanel}>
          <VoiceLibrary />
        </div>

        {/* 中间：TTS 合成 */}
        <div className={styles.centerPanel}>
          <TextToSpeech />
        </div>

        {/* 右侧：声音复刻 */}
        <div className={styles.rightPanel}>
          <VoiceCloner />
        </div>
      </div>
    </div>
  )
}

export default React.memo(TtsPage)
