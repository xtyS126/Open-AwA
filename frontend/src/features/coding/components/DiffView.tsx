/**
 * Diff 视图 — 基于 Monaco DiffEditor 的内联差异查看器。
 * 支持接受/拒绝更改、逐块导航。
 */
import React, { useCallback, useState } from 'react'
import { DiffEditor } from '@monaco-editor/react'
import { useThemeStore } from '@/shared/store/themeStore'
import styles from './DiffView.module.css'

interface DiffViewProps {
  original: string
  modified: string
  filePath: string
  language?: string
  onAccept?: () => void
  onReject?: () => void
}

const DiffView: React.FC<DiffViewProps> = ({
  original,
  modified,
  filePath,
  language,
  onAccept,
  onReject,
}) => {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const theme = useThemeStore(s => s.theme)
  const [accepted, setAccepted] = useState(false)

  const handleAccept = useCallback(() => {
    setAccepted(true)
    onAccept?.()
  }, [onAccept])

  const handleReject = useCallback(() => {
    onReject?.()
  }, [onReject])

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.fileName}>{filePath}</span>
        <div className={styles.actions}>
          <button className={styles.acceptBtn} onClick={handleAccept} disabled={accepted}>
            {accepted ? '已接受' : '接受更改'}
          </button>
          <button className={styles.rejectBtn} onClick={handleReject}>
            拒绝更改
          </button>
        </div>
      </div>
      <div className={styles.editor}>
        <DiffEditor
          height="100%"
          language={language}
          theme={theme === 'dark' ? 'vs-dark' : 'vs'}
          original={original}
          modified={modified}
          options={{
            readOnly: true,
            renderSideBySide: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            padding: { top: 8 },
          }}
        />
      </div>
    </div>
  )
}

export default React.memo(DiffView)
