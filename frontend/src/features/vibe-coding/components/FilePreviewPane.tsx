import { useEffect, useMemo, useState } from 'react'
import DOMPurify from 'dompurify'
import { AlertCircle, Download, Loader2, RefreshCw } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { api, API_BASE_URL } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import type { WorkbenchPreviewIntent } from '@/features/workbench/workbenchTypes'
import styles from './FilePreviewPane.module.css'

type PreviewMode = 'markdown' | 'image' | 'audio' | 'video' | 'office' | 'text' | 'unknown'

interface PreviewFileJsonResponse {
  type: 'markdown' | 'text' | 'download'
  html?: string
  content?: string
  url?: string
}

export interface FilePreviewPaneProps {
  projectId: string
  intent: WorkbenchPreviewIntent
}

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg'])
const VIDEO_EXTS = new Set(['mp4', 'webm'])
const MARKDOWN_EXTS = new Set(['md', 'markdown'])
const OFFICE_EXTS = new Set(['docx', 'xlsx', 'pptx'])
const TEXT_EXTS = new Set([
  'txt', 'log', 'py', 'js', 'ts', 'json', 'html', 'htm',
  'css', 'xml', 'yaml', 'yml', 'ini', 'toml', 'sh', 'bat', 'ps1',
])
const BINARY_EXTS = new Set([...IMAGE_EXTS, ...AUDIO_EXTS, ...VIDEO_EXTS])

function getExtension(path: string): string {
  return path.toLowerCase().split('.').pop() || ''
}

function getPreviewMode(path: string): PreviewMode {
  const extension = getExtension(path)
  if (MARKDOWN_EXTS.has(extension)) return 'markdown'
  if (IMAGE_EXTS.has(extension)) return 'image'
  if (AUDIO_EXTS.has(extension)) return 'audio'
  if (VIDEO_EXTS.has(extension)) return 'video'
  if (OFFICE_EXTS.has(extension)) return 'office'
  if (TEXT_EXTS.has(extension)) return 'text'
  return 'unknown'
}

function normalizeAuthenticatedDownloadUrl(relativeUrl: string): string | null {
  if (!relativeUrl.startsWith('/api/')) return null
  return relativeUrl.slice('/api'.length)
}

function buildPreviewUrl(projectId: string, previewId: string): string {
  const base = API_BASE_URL.replace(/\/$/, '')
  return `${base}/workbench/projects/${encodeURIComponent(projectId)}/previews/${encodeURIComponent(previewId)}/`
}

export default function FilePreviewPane({ projectId, intent }: FilePreviewPaneProps) {
  const { t } = useI18nStore()
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('unknown')
  const [markdownHtml, setMarkdownHtml] = useState('')
  const [textContent, setTextContent] = useState('')
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [downloadRequestUrl, setDownloadRequestUrl] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const relativePath = intent.kind === 'file' ? intent.relativePath : null
  const sanitizedMarkdownHtml = useMemo(() => DOMPurify.sanitize(markdownHtml, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'code', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'a', 'img', 'blockquote', 'table', 'thead', 'tbody',
      'tr', 'th', 'td', 'hr', 'span', 'div', 'del', 'sub', 'sup',
    ],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class'],
    ALLOW_DATA_ATTR: false,
  }), [markdownHtml])

  useEffect(() => {
    let disposed = false
    let createdObjectUrl: string | null = null

    setLoading(false)
    setError(null)
    setMarkdownHtml('')
    setTextContent('')
    setObjectUrl(null)
    setDownloadRequestUrl(null)
    setDownloading(false)

    if (!relativePath) {
      return () => {
        disposed = true
      }
    }

    const mode = getPreviewMode(relativePath)
    setPreviewMode(mode)
    setLoading(true)

    const load = async (): Promise<void> => {
      try {
        const endpoint = `/workbench/projects/${encodeURIComponent(projectId)}/files/preview`
        const params = { path: relativePath }
        if (BINARY_EXTS.has(getExtension(relativePath))) {
          const response = await api.get<Blob>(endpoint, {
            params,
            responseType: 'blob',
          })
          if (disposed) return
          createdObjectUrl = URL.createObjectURL(response.data)
          setObjectUrl(createdObjectUrl)
          return
        }

        const response = await api.get<PreviewFileJsonResponse>(endpoint, { params })
        if (disposed) return
        if (response.data.type === 'markdown') {
          setMarkdownHtml(response.data.html || '')
          setPreviewMode('markdown')
        } else if (response.data.type === 'text') {
          setTextContent(response.data.content || '')
          setPreviewMode('text')
        } else {
          setDownloadRequestUrl(
            response.data.url ? normalizeAuthenticatedDownloadUrl(response.data.url) : null,
          )
          setPreviewMode('office')
        }
      } catch (loadError) {
        if (disposed) return
        const message = loadError instanceof Error ? loadError.message : String(loadError)
        setError(message)
        appLogger.error({
          event: 'file_preview_load_failed',
          module: 'vibe-coding',
          action: 'preview',
          status: 'failure',
          message: '文件预览加载失败',
          extra: { project_id: projectId, path: relativePath, error: message },
        })
      } finally {
        if (!disposed) setLoading(false)
      }
    }

    void load()
    return () => {
      disposed = true
      if (createdObjectUrl) URL.revokeObjectURL(createdObjectUrl)
    }
  }, [projectId, refreshKey, relativePath])

  const handleAuthenticatedDownload = async (): Promise<void> => {
    if (!downloadRequestUrl || !relativePath || downloading) return
    setDownloading(true)
    try {
      const response = await api.get<Blob>(downloadRequestUrl, { responseType: 'blob' })
      const blobUrl = URL.createObjectURL(response.data)
      const anchor = document.createElement('a')
      anchor.href = blobUrl
      anchor.download = relativePath.split('/').pop() || 'download'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(blobUrl)
    } catch (downloadError) {
      const message = downloadError instanceof Error ? downloadError.message : String(downloadError)
      setError(message)
      appLogger.error({
        event: 'file_preview_download_failed',
        module: 'vibe-coding',
        action: 'download',
        status: 'failure',
        message: '文件下载失败',
        extra: { project_id: projectId, path: relativePath, error: message },
      })
    } finally {
      setDownloading(false)
    }
  }

  if (intent.kind === 'web') {
    return (
      <div className={styles.root}>
        <div className={styles['web-frame']}>
          <iframe
            src={buildPreviewUrl(projectId, intent.previewId)}
            className={styles.iframe}
            title={t('vibeCoding.filePreview.webPreview')}
            sandbox="allow-scripts allow-forms"
          />
        </div>
      </div>
    )
  }

  return (
    <div className={styles.root}>
      {relativePath && (
        <div className={styles.toolbar}>
          <span className={styles.path} title={relativePath}>{relativePath}</span>
          <button
            type="button"
            className={styles['action-btn']}
            onClick={() => setRefreshKey((value) => value + 1)}
            disabled={loading}
            title={t('vibeCoding.filePreview.refresh')}
          >
            <RefreshCw size={14} />
            <span>{t('vibeCoding.filePreview.refresh')}</span>
          </button>
        </div>
      )}

      <div className={styles['preview-area']}>
        {loading && (
          <div className={styles['state-box']}>
            <Loader2 size={24} className={styles.spinner} />
            <span className={styles['state-text']}>{t('vibeCoding.filePreview.loading')}</span>
          </div>
        )}

        {!loading && error && (
          <div className={styles['state-box']}>
            <AlertCircle size={24} className={styles['error-icon']} />
            <span className={styles['state-text']}>{t('vibeCoding.filePreview.error')}: {error}</span>
          </div>
        )}

        {!loading && !error && !relativePath && (
          <div className={styles['state-box']}>
            <span className={styles['state-text']}>请选择文件或创建网页预览</span>
          </div>
        )}

        {!loading && !error && relativePath && previewMode === 'markdown' && (
          <div
            className={styles['markdown-content']}
            dangerouslySetInnerHTML={{ __html: sanitizedMarkdownHtml }}
          />
        )}

        {!loading && !error && relativePath && previewMode === 'text' && (
          <pre className={styles['text-content']}><code>{textContent}</code></pre>
        )}

        {!loading && !error && relativePath && previewMode === 'image' && objectUrl && (
          <div className={styles['media-wrap']}>
            <img src={objectUrl} alt={relativePath} className={styles.image} />
          </div>
        )}

        {!loading && !error && relativePath && previewMode === 'audio' && objectUrl && (
          <div className={styles['media-wrap']}><audio controls src={objectUrl} className={styles.audio} /></div>
        )}

        {!loading && !error && relativePath && previewMode === 'video' && objectUrl && (
          <div className={styles['media-wrap']}><video controls src={objectUrl} className={styles.video} /></div>
        )}

        {!loading && !error && relativePath && (previewMode === 'office' || previewMode === 'unknown') && (
          <div className={styles['state-box']}>
            <Download size={24} className={styles['state-icon']} />
            <span className={styles['state-text']}>{t('vibeCoding.filePreview.unsupported')}</span>
            {downloadRequestUrl && (
              <button
                type="button"
                className={styles['download-link']}
                disabled={downloading}
                onClick={() => void handleAuthenticatedDownload()}
              >
                <Download size={14} />
                {downloading ? '下载中' : t('vibeCoding.filePreview.download')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
