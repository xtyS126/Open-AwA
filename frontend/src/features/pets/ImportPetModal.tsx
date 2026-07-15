/**
 * ImportPetModal ?? ??????????
 *
 * ?????????
 *   - ?????pet.json ?? + ??????webp/png/gif?
 *   - ???????????? zip ??
 * ??????? /api/pets/import???????????????
 */
import { useState, type ChangeEvent } from 'react'
import { Upload, FileText, Image as ImageIcon, Archive, X, Loader2 } from 'lucide-react'
import { importPet, type ImportPetFiles } from './petsApi'
import type { PetResponse } from './types'
import styles from './ImportPetModal.module.css'

interface ImportPetModalProps {
  /** ?????? */
  onClose: () => void
  /** ???????????/????? */
  onSuccess?: (pet: PetResponse) => void
}

type ImportMode = 'files' | 'archive'

/** ?????????????? */
function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { data?: { detail?: string } }; message?: string }
  const detail = maybeError?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  const message = maybeError?.message
  if (typeof message === 'string' && message.trim()) return message
  return fallback
}

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
      setError(getErrorMessage(err, '?????????????'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" onClick={onClose}>
      <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>???????</h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="??">
            <X size={18} />
          </button>
        </div>

        <div className={styles.modeTabs}>
          <button
            type="button"
            className={mode === 'files' ? styles.tabActive : styles.tab}
            onClick={() => { setMode('files'); setError(null) }}
          >
            <FileText size={14} /> ????
          </button>
          <button
            type="button"
            className={mode === 'archive' ? styles.tabActive : styles.tab}
            onClick={() => { setMode('archive'); setError(null) }}
          >
            <Archive size={14} /> ????
          </button>
        </div>

        <div className={styles.body}>
          {mode === 'files' ? (
            <>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <FileText size={14} /> pet.json ??
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
                  <ImageIcon size={14} /> ??????webp/png/gif?
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
                V2 ???? 1536x2288?8 ? 11 ??192x208 ???V1 ? 1536x1872?8x9?
              </p>
            </>
          ) : (
            <>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <Archive size={14} /> zip ?????? pet.json ?????
                </span>
                <input
                  type="file"
                  accept="application/zip,.zip"
                  onChange={onPick(setArchiveFile)}
                  className={styles.fileInput}
                />
                {archiveFile && <span className={styles.fileName}>{archiveFile.name}</span>}
              </label>
              <p className={styles.tip}>???????? hatch-pet ??? pet.json ? spritesheet.webp?</p>
            </>
          )}

          {error && <p className={styles.error}>{error}</p>}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.btnGhost} onClick={onClose} disabled={submitting}>
            ??
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {submitting ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
            {submitting ? '????' : '????'}
          </button>
        </div>
      </div>
    </div>
  )
}
