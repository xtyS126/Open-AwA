/**
 * ImportPetModal 导入自定义宠物对话框
 *
 * 支持两种导入方式：
 *   - 文件模式（pet.json 清单 + 精灵表图片 webp/png/gif）
 *   - 归档模式（包含上述文件的 zip 归档）
 * 提交至 /api/pets/import，成功后回调并自动关闭。
 */
import { useState, type ChangeEvent } from 'react'
import { Upload, FileText, Image as ImageIcon, Archive, X, Loader2 } from 'lucide-react'
import { importPet, type ImportPetFiles } from './petsApi'
import type { PetResponse } from './types'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './ImportPetModal.module.css'

interface ImportPetModalProps {
  /** 关闭回调 */
  onClose: () => void
  /** 导入成功回调（可选，收到新建宠物） */
  onSuccess?: (pet: PetResponse) => void
}

type ImportMode = 'files' | 'archive'

/** 从未知错误中尽量提取可读信息 */
export default function ImportPetModal({ onClose, onSuccess }: ImportPetModalProps) {
  const [mode, setMode] = useState<ImportMode>('files')
  const [manifestFile, setManifestFile] = useState<File | null>(null)
  const [spritesheetFile, setSpritesheetFile] = useState<File | null>(null)
  const [archiveFile, setArchiveFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onPick = (setter: (file: File | null) => void) => (event: ChangeEvent<HTMLInputElement>) => {
    setError(null)
    setter(event.target.files?.[0] ?? null)
  }

  const canSubmit =
    !submitting &&
    (mode === 'archive'
      ? !!archiveFile
      : !!manifestFile && !!spritesheetFile)

  const handleSubmit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const files: ImportPetFiles =
        mode === 'archive'
          ? { archive: archiveFile }
          : { manifest: manifestFile, spritesheet: spritesheetFile }
      const pet = await importPet(files)
      onSuccess?.(pet)
      onClose()
    } catch (err) {
      setError(getErrorMessage(err, '导入失败，请稍后重试'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" onClick={onClose}>
      <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>导入自定义宠物</h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        <div className={styles.modeTabs}>
          <button
            type="button"
            className={mode === 'files' ? styles.tabActive : styles.tab}
            onClick={() => { setMode('files'); setError(null) }}
          >
            <FileText size={14} /> 文件模式
          </button>
          <button
            type="button"
            className={mode === 'archive' ? styles.tabActive : styles.tab}
            onClick={() => { setMode('archive'); setError(null) }}
          >
            <Archive size={14} /> 归档模式
          </button>
        </div>

        <div className={styles.body}>
          {mode === 'files' ? (
            <>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <FileText size={14} /> pet.json 清单
                </span>
                <input
                  type="file"
                  accept="application/json,.json"
                  onChange={onPick(setManifestFile)}
                  className={styles.fileInput}
                />
                {manifestFile && <span className={styles.fileName}>{manifestFile.name}</span>}
              </label>

              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <ImageIcon size={14} /> 精灵表图片（webp/png/gif）
                </span>
                <input
                  type="file"
                  accept="image/webp,image/png,image/gif,.webp,.png,.gif"
                  onChange={onPick(setSpritesheetFile)}
                  className={styles.fileInput}
                />
                {spritesheetFile && <span className={styles.fileName}>{spritesheetFile.name}</span>}
              </label>

              <p className={styles.tip}>
                V2 推荐 1536x2288（8 列 11 行，192x208）；V1 为 1536x1872（8x9）。
              </p>
            </>
          ) : (
            <>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <Archive size={14} /> zip 归档需包含 pet.json 与精灵表
                </span>
                <input
                  type="file"
                  accept="application/zip,.zip"
                  onChange={onPick(setArchiveFile)}
                  className={styles.fileInput}
                />
                {archiveFile && <span className={styles.fileName}>{archiveFile.name}</span>}
              </label>
              <p className={styles.tip}>可使用 hatch-pet 工具生成 pet.json 与 spritesheet.webp。</p>
            </>
          )}

          {error && <p className={styles.error}>{error}</p>}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.btnGhost} onClick={onClose} disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {submitting ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
            {submitting ? '导入中...' : '开始导入'}
          </button>
        </div>
      </div>
    </div>
  )
}
