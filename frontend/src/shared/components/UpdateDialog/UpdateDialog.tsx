import { useI18nStore } from '@/i18n'
import type { UpdateInfo } from '@/shared/api/updateApi'
import type { UpdateProgress, UpdateStatus } from '@/shared/hooks/useAppUpdate'
import styles from './UpdateDialog.module.css'

interface UpdateDialogProps {
  info: UpdateInfo
  status: UpdateStatus
  progress: UpdateProgress | null
  error?: string
  onUpdate: () => void
  onLater: () => void
}

function formatSize(bytes: number): string {
  if (bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(2)} MB`
}

/** APP 更新弹窗：版本信息 + changelog + 下载进度 + 立即更新/稍后 */
export function UpdateDialog({ info, status, progress, error, onUpdate, onLater }: UpdateDialogProps) {
  const { t } = useI18nStore()
  const downloading = status === 'downloading'
  const installing = status === 'installing'
  const failed = status === 'error'
  const percent = progress?.percent ?? 0

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={t('update.title')}>
      <div className={styles.dialog}>
        <div className={styles.icon} aria-hidden="true">⬆</div>
        <h2 className={styles.title}>{t('update.title')}</h2>
        <p className={styles.subtitle}>
          {t('update.currentToLatest', { latest: info.latest_version })}
        </p>
        {info.changelog && (
          <div className={styles.changelog}>
            <h3>{t('update.changelog')}</h3>
            <pre className={styles.changelogText}>{info.changelog}</pre>
          </div>
        )}
        <p className={styles.meta}>
          {t('update.packageSize')}: {formatSize(info.apk_size)}
        </p>

        {downloading && (
          <div className={styles.progressWrap}>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${percent}%` }} />
            </div>
            <span className={styles.progressText}>{percent}%</span>
          </div>
        )}
        {installing && <p className={styles.installing}>{t('update.installing')}</p>}
        {failed && <p className={styles.error} role="alert">{error || t('update.downloadFailed')}</p>}

        <div className={styles.actions}>
          {!downloading && !installing && (
            <button type="button" className={styles.laterBtn} onClick={onLater} data-testid="update-later">
              {t('update.later')}
            </button>
          )}
          {!downloading && !installing && (
            <button type="button" className={styles.updateBtn} onClick={onUpdate} data-testid="update-now">
              {t('update.now')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default UpdateDialog
