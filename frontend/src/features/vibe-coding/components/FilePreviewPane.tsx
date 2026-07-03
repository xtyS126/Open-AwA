/**
 * 文件预览面板组件 —— vibe-coding 右栏。
 *
 * 按扩展名分发渲染：
 *   - Markdown：后端渲染为已净化的 HTML，前端用 dangerouslySetInnerHTML 显示
 *   - 图片/音频/视频：用 axios 获取 blob 后通过 URL.createObjectURL 渲染（端点需 Bearer 鉴权，无法用裸标签 src）
 *   - Office/未知/文本：端点返回 JSON，按 type 字段分发（下载链接 / 文本内容）
 *   - 网页预览：当 previewPort 有效时，用 iframe 反向代理到本地开发服务器
 *
 * 状态管理：内部维护输入框路径、当前预览路径、加载/错误状态等。
 * 组件卸载时自动 revoke object URL，防止内存泄漏。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import { AlertCircle, Download, ExternalLink, Loader2, RefreshCw, Search } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { api, API_BASE_URL } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import styles from './FilePreviewPane.module.css'

/** 预览模式 —— 由文件扩展名推断，决定渲染路径 */
type PreviewMode =
  | 'markdown'
  | 'image'
  | 'audio'
  | 'video'
  | 'office'
  | 'text'
  | 'unknown'
  | 'web'

/** 预览端点 JSON 响应体（Markdown/文本/Office/未知类型共用） */
interface PreviewFileJsonResponse {
  type: 'markdown' | 'text' | 'download'
  html?: string
  content?: string
  mime?: string
  url?: string
  error?: string
}

export interface FilePreviewPaneProps {
  /** 外部传入的文件路径，变化时自动加载 */
  filePath: string | null
  /** 网页预览端口（如 5173），非空时切换到 iframe 网页预览模式 */
  previewPort?: number | null
}

/* ===== 扩展名集合 —— 与后端 coding.py 的 MIME 映射对齐 ===== */

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg'])
const VIDEO_EXTS = new Set(['mp4', 'webm'])
const MARKDOWN_EXTS = new Set(['md', 'markdown'])
const OFFICE_EXTS = new Set(['docx', 'xlsx', 'pptx'])
const TEXT_EXTS = new Set([
  'txt', 'log', 'py', 'js', 'ts', 'json', 'html', 'htm',
  'css', 'xml', 'yaml', 'yml', 'ini', 'toml', 'sh', 'bat', 'ps1',
])

/** 二进制类型集合 —— 需用 blob 方式获取 */
const BINARY_EXTS = new Set([...IMAGE_EXTS, ...AUDIO_EXTS, ...VIDEO_EXTS])

/** 根据文件路径推断预览模式 */
function getPreviewMode(path: string): PreviewMode {
  const ext = path.toLowerCase().split('.').pop() || ''
  if (MARKDOWN_EXTS.has(ext)) return 'markdown'
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (AUDIO_EXTS.has(ext)) return 'audio'
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (OFFICE_EXTS.has(ext)) return 'office'
  if (TEXT_EXTS.has(ext)) return 'text'
  return 'unknown'
}

/** 将后端返回的相对下载 URL 解析为浏览器可访问的完整 URL */
function resolveDownloadUrl(relativeUrl: string): string {
  if (/^https?:\/\//i.test(relativeUrl)) return relativeUrl
  try {
    const baseOrigin = new URL(API_BASE_URL, window.location.origin).origin
    return baseOrigin + relativeUrl
  } catch {
    return relativeUrl
  }
}

export default function FilePreviewPane({ filePath, previewPort }: FilePreviewPaneProps) {
  const { t } = useI18nStore()
  const [inputPath, setInputPath] = useState('')
  const [inputPort, setInputPort] = useState('')
  const [currentPath, setCurrentPath] = useState<string | null>(null)
  const [activePort, setActivePort] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('unknown')
  const [markdownHtml, setMarkdownHtml] = useState('')
  const [textContent, setTextContent] = useState('')
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [officeDownloadUrl, setOfficeDownloadUrl] = useState<string | null>(null)
  const [iframeKey, setIframeKey] = useState(0)

  // 跟踪当前 object URL，便于卸载/切换时 revoke
  const objectUrlRef = useRef<string | null>(null)

  /** 释放当前持有的 object URL */
  const revokeObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
    setObjectUrl(null)
  }, [])

  // 后端返回的 markdown HTML 二次净化 —— 即便后端已净化，前端仍做兜底以防御 XSS
  const sanitizedMarkdownHtml = useMemo(() => {
    if (!markdownHtml) return ''
    return DOMPurify.sanitize(markdownHtml, {
      // 允许常用 Markdown 渲染标签，禁用 script/iframe/form 等危险标签
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'code', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'a', 'img', 'blockquote', 'table', 'thead', 'tbody',
        'tr', 'th', 'td', 'hr', 'span', 'div', 'del', 'sub', 'sup',
      ],
      // 仅允许安全属性，禁止 on* 事件处理器
      ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class'],
      ALLOW_DATA_ATTR: false,
    })
  }, [markdownHtml])

  /** 加载文件预览 —— 按扩展名决定 blob 或 JSON 获取方式 */
  const loadPreview = useCallback(
    async (path: string) => {
      // 清理上一次预览的状态
      revokeObjectUrl()
      setMarkdownHtml('')
      setTextContent('')
      setOfficeDownloadUrl(null)
      setError(null)
      setLoading(true)

      const mode = getPreviewMode(path)
      setPreviewMode(mode)

      try {
        if (BINARY_EXTS.has(path.toLowerCase().split('.').pop() || '')) {
          // 二进制文件：以 blob 方式获取，避免裸标签无法附加 Authorization 头
          const response = await api.get<Blob>('/coding/preview/file', {
            params: { path },
            responseType: 'blob',
          })
          const url = URL.createObjectURL(response.data)
          objectUrlRef.current = url
          setObjectUrl(url)
        } else {
          // JSON 响应：Markdown 渲染 HTML / 文本内容 / 下载链接
          const response = await api.get<PreviewFileJsonResponse>('/coding/preview/file', {
            params: { path },
          })
          const data = response.data
          if (data.type === 'markdown') {
            setMarkdownHtml(data.html || '')
            setPreviewMode('markdown')
          } else if (data.type === 'text') {
            setTextContent(data.content || '')
            setPreviewMode('text')
          } else if (data.type === 'download') {
            setOfficeDownloadUrl(data.url ? resolveDownloadUrl(data.url) : null)
            setPreviewMode('office')
          }
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        setError(message)
        appLogger.error({
          event: 'file_preview_load_failed',
          module: 'vibe-coding',
          action: 'preview',
          status: 'failure',
          message: '文件预览加载失败',
          extra: { path, error: message },
        })
      } finally {
        setLoading(false)
      }
    },
    [revokeObjectUrl],
  )

  /** 监听外部 filePath 变化，同步到输入框并触发加载 */
  useEffect(() => {
    if (filePath) {
      setInputPath(filePath)
      setCurrentPath(filePath)
      setActivePort(null)
      setInputPort('')
    }
  }, [filePath])

  /** 监听外部 previewPort 变化 */
  useEffect(() => {
    if (previewPort != null) {
      setInputPort(String(previewPort))
      setActivePort(previewPort)
    }
  }, [previewPort])

  /** currentPath 变化时加载文件预览 */
  useEffect(() => {
    if (currentPath && activePort == null) {
      void loadPreview(currentPath)
    }
  }, [currentPath, activePort, loadPreview])

  /** 组件卸载时释放 object URL，防止内存泄漏 */
  useEffect(() => {
    return () => {
      revokeObjectUrl()
    }
  }, [revokeObjectUrl])

  /** 输入框回车 / 点击预览按钮 —— 提交路径并切换到文件模式 */
  const handleSubmitPath = useCallback(() => {
    const trimmed = inputPath.trim()
    if (!trimmed) return
    setActivePort(null)
    setInputPort('')
    setCurrentPath(trimmed)
  }, [inputPath])

  /** 端口输入提交 —— 切换到网页预览模式 */
  const handleSubmitPort = useCallback(() => {
    const trimmed = inputPort.trim()
    if (!trimmed) {
      setActivePort(null)
      return
    }
    const port = Number(trimmed)
    if (Number.isNaN(port) || port < 1024 || port > 65535) {
      setError(t('vibeCoding.filePreview.error') + ': port 1024-65535')
      setActivePort(null)
      return
    }
    setError(null)
    setActivePort(port)
    setIframeKey((k) => k + 1)
  }, [inputPort, t])

  /** 刷新当前预览 */
  const handleRefresh = useCallback(() => {
    if (activePort != null) {
      setIframeKey((k) => k + 1)
    } else if (currentPath) {
      void loadPreview(currentPath)
    }
  }, [activePort, currentPath, loadPreview])

  /** 清除端口，回到文件预览模式 */
  const handleClearPort = useCallback(() => {
    setActivePort(null)
    setInputPort('')
  }, [])

  const isWebMode = activePort != null

  return (
    <div className={styles.root}>
      {/* 顶部输入栏 */}
      <div className={styles['input-bar']}>
        <div className={styles['input-row']}>
          <input
            type="text"
            className={styles['path-input']}
            value={inputPath}
            onChange={(e) => setInputPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmitPath()
            }}
            placeholder={t('vibeCoding.filePreview.pathPlaceholder')}
            spellCheck={false}
          />
          <button
            type="button"
            className={styles['action-btn']}
            onClick={handleSubmitPath}
            title={t('vibeCoding.filePreview.preview')}
          >
            <Search size={14} />
          </button>
        </div>
        <div className={styles['input-row']}>
          <input
            type="text"
            className={styles['port-input']}
            value={inputPort}
            onChange={(e) => setInputPort(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmitPort()
            }}
            placeholder={t('vibeCoding.filePreview.portPlaceholder')}
            spellCheck={false}
            inputMode="numeric"
          />
          {isWebMode ? (
            <button
              type="button"
              className={styles['action-btn']}
              onClick={handleClearPort}
              title={t('vibeCoding.filePreview.preview')}
            >
              <ExternalLink size={14} />
            </button>
          ) : (
            <button
              type="button"
              className={styles['action-btn']}
              onClick={handleSubmitPort}
              title={t('vibeCoding.filePreview.webPreview')}
            >
              <ExternalLink size={14} />
            </button>
          )}
        </div>
        <button
          type="button"
          className={`${styles['action-btn']} ${styles['refresh-btn']}`}
          onClick={handleRefresh}
          disabled={loading || (!currentPath && !isWebMode)}
          title={t('vibeCoding.filePreview.refresh')}
        >
          <RefreshCw size={14} />
          <span>{t('vibeCoding.filePreview.refresh')}</span>
        </button>
      </div>

      {/* 预览区 */}
      <div className={styles['preview-area']}>
        {loading && (
          <div className={styles['state-box']}>
            <Loader2 size={24} className={styles['spinner']} />
            <span className={styles['state-text']}>
              {t('vibeCoding.filePreview.loading')}
            </span>
          </div>
        )}

        {!loading && error && (
          <div className={styles['state-box']}>
            <AlertCircle size={24} className={styles['error-icon']} />
            <span className={styles['state-text']}>
              {t('vibeCoding.filePreview.error')}: {error}
            </span>
            <button
              type="button"
              className={styles['action-btn']}
              onClick={handleRefresh}
            >
              {t('vibeCoding.filePreview.retry')}
            </button>
          </div>
        )}

        {!loading && !error && isWebMode && activePort != null && (
          <div className={styles['web-frame']}>
            <iframe
              key={iframeKey}
              src={`${API_BASE_URL}/preview/${activePort}/`}
              className={styles.iframe}
              title={t('vibeCoding.filePreview.webPreview')}
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          </div>
        )}

        {!loading && !error && !isWebMode && !currentPath && (
          <div className={styles['state-box']}>
            <span className={styles['state-text']}>
              {t('vibeCoding.filePreview.empty')}
            </span>
          </div>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'markdown' && (
          <div
            className={styles['markdown-content']}
            dangerouslySetInnerHTML={{ __html: sanitizedMarkdownHtml }}
          />
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'text' && (
          <pre className={styles['text-content']}>
            <code>{textContent}</code>
          </pre>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'image' && objectUrl && (
          <div className={styles['media-wrap']}>
            <img
              src={objectUrl}
              alt={currentPath}
              className={styles.image}
            />
          </div>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'audio' && objectUrl && (
          <div className={styles['media-wrap']}>
            <audio controls src={objectUrl} className={styles.audio} />
          </div>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'video' && objectUrl && (
          <div className={styles['media-wrap']}>
            <video controls src={objectUrl} className={styles.video} />
          </div>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'office' && (
          <div className={styles['state-box']}>
            <Download size={24} className={styles['state-icon']} />
            <span className={styles['state-text']}>
              {t('vibeCoding.filePreview.unsupported')}
            </span>
            {officeDownloadUrl && (
              <a
                href={officeDownloadUrl}
                className={styles['download-link']}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Download size={14} />
                {t('vibeCoding.filePreview.download')}
              </a>
            )}
          </div>
        )}

        {!loading && !error && !isWebMode && currentPath && previewMode === 'unknown' && (
          <div className={styles['state-box']}>
            <AlertCircle size={24} className={styles['state-icon']} />
            <span className={styles['state-text']}>
              {t('vibeCoding.filePreview.unsupported')}
            </span>
            {officeDownloadUrl && (
              <a
                href={officeDownloadUrl}
                className={styles['download-link']}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Download size={14} />
                {t('vibeCoding.filePreview.download')}
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
