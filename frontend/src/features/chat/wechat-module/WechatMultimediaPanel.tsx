import { useState, useEffect, useCallback, useMemo } from 'react'
import { Image as ImageIcon, Mic, FileText, Video, RefreshCw, Send, Filter } from 'lucide-react'
import { useToast } from '@/shared/components/Toast'
import {
  listMultimedia,
  sendMultimedia,
  type WeixinMultimediaMessage,
  type WeixinMediaType,
} from '@/shared/api/weixinMultimediaApi'
import styles from './WechatConfigModule.module.css'

/** 多媒体类型过滤器选项 */
type FilterType = 'all' | WeixinMediaType

/** 多媒体类型图标映射 */
const MEDIA_TYPE_ICONS: Record<string, React.ReactNode> = {
  image: <ImageIcon size={16} />,
  voice: <Mic size={16} />,
  file: <FileText size={16} />,
  video: <Video size={16} />,
}

/** 多媒体类型中文标签映射 */
const MEDIA_TYPE_LABELS: Record<string, string> = {
  image: '图片',
  voice: '语音',
  file: '文件',
  video: '视频',
}

/** 文件大小格式化为人类可读字符串 */
function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

/** 时长格式化（毫秒转秒） */
function formatDuration(ms: number): string {
  if (!ms || ms <= 0) return ''
  if (ms < 1000) return `${ms} 毫秒`
  return `${(ms / 1000).toFixed(1)} 秒`
}

/** 时间戳格式化 */
function formatTimestamp(ts: string): string {
  if (!ts) return '-'
  try {
    return new Date(ts).toLocaleString('zh-CN')
  } catch {
    return ts
  }
}

/** MIME 类型到 media_type 的映射，用于自动推断消息类型 */
const MIME_TO_MEDIA_TYPE: Record<string, WeixinMediaType> = {
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/gif': 'image',
  'audio/amr': 'voice',
  'audio/mp3': 'voice',
  'audio/mpeg': 'voice',
  'video/mp4': 'video',
  'application/pdf': 'file',
}

export default function WechatMultimediaPanel() {
  const { addToast, ToastContainer } = useToast()

  // 多媒体消息列表状态
  const [messages, setMessages] = useState<WeixinMultimediaMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [filterType, setFilterType] = useState<FilterType>('all')

  // 发送表单状态
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [toUser, setToUser] = useState('')
  const [mediaType, setMediaType] = useState<WeixinMediaType>('image')
  const [sending, setSending] = useState(false)

  /** 加载多媒体消息列表 */
  const loadMessages = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const params = filterType === 'all' ? { limit: 50 } : { limit: 50, media_type: filterType }
      const result = await listMultimedia(params)
      setMessages(result)
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : '加载多媒体消息失败'
      setLoadError(errorMsg)
    } finally {
      setLoading(false)
    }
  }, [filterType])

  // 初始加载和过滤器变化时重新加载
  useEffect(() => {
    void loadMessages()
  }, [loadMessages])

  /** 文件选择处理，自动推断消息类型 */
  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null
    setSelectedFile(file)
    if (file && file.type) {
      const inferred = MIME_TO_MEDIA_TYPE[file.type]
      if (inferred) {
        setMediaType(inferred)
      }
    }
  }, [])

  /** 发送多媒体消息 */
  const handleSend = useCallback(async () => {
    if (!selectedFile) {
      addToast('请先选择要发送的文件', 'warning')
      return
    }
    if (!toUser.trim()) {
      addToast('请输入目标用户 ID', 'warning')
      return
    }
    setSending(true)
    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('to_user', toUser.trim())
      formData.append('media_type', mediaType)
      const result = await sendMultimedia(formData)
      if (result.success) {
        addToast(`多媒体消息发送成功: ${MEDIA_TYPE_LABELS[result.media_type] || result.media_type}`, 'success')
        setSelectedFile(null)
        // 重置 file input
        const fileInput = document.getElementById('weixin-multimedia-file-input') as HTMLInputElement | null
        if (fileInput) fileInput.value = ''
        // 刷新消息列表
        void loadMessages()
      } else {
        addToast('发送失败，请重试', 'error')
      }
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : '发送多媒体消息失败'
      addToast(errorMsg, 'error')
    } finally {
      setSending(false)
    }
  }, [selectedFile, toUser, mediaType, addToast, loadMessages])

  /** 过滤后的消息列表 */
  const filteredMessages = useMemo(() => {
    return messages
  }, [messages])

  /** 过滤器按钮配置 */
  const filterOptions: Array<{ value: FilterType; label: string }> = [
    { value: 'all', label: '全部' },
    { value: 'image', label: '图片' },
    { value: 'voice', label: '语音' },
    { value: 'file', label: '文件' },
    { value: 'video', label: '视频' },
  ]

  return (
    <div className={styles['qr-login']}>
      <ToastContainer />
      <h4 className={styles['qr-login-title']}>多媒体消息管理</h4>
      <p className={styles['qr-login-desc']}>
        查看收到的多媒体消息列表，并支持上传文件发送给指定微信用户。
      </p>

      {/* 多媒体消息列表区域 */}
      <div style={{ marginBottom: '24px' }}>
        <div className={styles['actions-row']} style={{ marginTop: '0', marginBottom: '16px', alignItems: 'center' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '14px', color: 'var(--color-text-secondary)' }}>
            <Filter size={14} />
            类型过滤:
          </span>
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              className={`btn ${filterType === opt.value ? 'btn-primary' : styles['btn-secondary'] || 'btn-secondary'}`}
              style={{ padding: '4px 12px', fontSize: '13px' }}
              onClick={() => setFilterType(opt.value)}
              disabled={loading}
            >
              {opt.label}
            </button>
          ))}
          <button
            className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
            style={{ padding: '4px 12px', fontSize: '13px', marginLeft: 'auto' }}
            onClick={() => void loadMessages()}
            disabled={loading}
          >
            <RefreshCw size={14} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
            {loading ? '加载中...' : '刷新'}
          </button>
        </div>

        {loadError && (
          <div className={`${styles['message']} ${styles['error']}`} style={{ marginBottom: '12px' }}>
            {loadError}
          </div>
        )}

        {loading && filteredMessages.length === 0 ? (
          <p className={styles['loading']}>加载多媒体消息中...</p>
        ) : filteredMessages.length === 0 ? (
          <p className={styles['qr-status']}>暂无多媒体消息记录</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '400px', overflowY: 'auto' }}>
            {filteredMessages.map((msg) => (
              <div
                key={msg.message_id}
                style={{
                  padding: '12px',
                  background: 'var(--color-bg)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--color-border)',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '12px',
                }}
              >
                <span style={{ flexShrink: 0, color: 'var(--color-primary)', marginTop: '2px' }}>
                  {MEDIA_TYPE_ICONS[msg.media_type] ?? <FileText size={16} />}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 500 }}>
                      {MEDIA_TYPE_LABELS[msg.media_type] ?? msg.message_type}
                      {msg.file_name ? ` - ${msg.file_name}` : ''}
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                      {formatTimestamp(msg.timestamp)}
                    </span>
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
                    <span>发送者: {msg.from_user_id || '-'}</span>
                    {msg.file_size > 0 && <span>大小: {formatFileSize(msg.file_size)}</span>}
                    {msg.duration_ms > 0 && <span>时长: {formatDuration(msg.duration_ms)}</span>}
                    {msg.media_format && <span>格式: {msg.media_format}</span>}
                  </div>
                  {msg.text && (
                    <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {msg.text}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 发送多媒体消息表单 */}
      <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: '20px' }}>
        <h5 style={{ margin: '0 0 12px', fontSize: '15px', fontWeight: 600 }}>发送多媒体消息</h5>
        <div className={styles['form-item']}>
          <label className={styles['label']}>目标用户 ID <span className={styles['required']}>*</span></label>
          <input
            type="text"
            value={toUser}
            onChange={(e) => setToUser(e.target.value)}
            placeholder="输入微信用户 ID"
            className={styles['input']}
            disabled={sending}
          />
        </div>
        <div className={styles['form-item']}>
          <label className={styles['label']}>消息类型 <span className={styles['required']}>*</span></label>
          <select
            value={mediaType}
            onChange={(e) => setMediaType(e.target.value as WeixinMediaType)}
            className={styles['input']}
            disabled={sending}
          >
            <option value="image">图片 (image)</option>
            <option value="voice">语音 (voice)</option>
            <option value="video">视频 (video)</option>
            <option value="file">文件 (file)</option>
          </select>
        </div>
        <div className={styles['form-item']}>
          <label className={styles['label']}>选择文件 <span className={styles['required']}>*</span></label>
          <input
            id="weixin-multimedia-file-input"
            type="file"
            onChange={handleFileChange}
            disabled={sending}
            style={{ width: '100%', fontSize: '14px' }}
          />
          {selectedFile && (
            <p className={styles['qr-status']} style={{ marginTop: '8px' }}>
              已选择: {selectedFile.name} ({formatFileSize(selectedFile.size)})
            </p>
          )}
        </div>
        <div className={styles['actions-row']}>
          <button
            className="btn btn-primary"
            onClick={() => void handleSend()}
            disabled={sending || !selectedFile || !toUser.trim()}
          >
            {sending ? (
              '发送中...'
            ) : (
              <>
                <Send size={14} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                发送消息
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
