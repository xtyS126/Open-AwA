import { useState, useRef, useCallback, useEffect } from 'react'
import { X, Paperclip, Send, Square } from 'lucide-react'
import { appLogger } from '@/shared/utils/logger'
import { useI18nStore, t as i18nT } from '@/i18n'
import styles from './ChatInput.module.css'

export interface FileAttachment {
  id: string
  file: File
  preview?: string
  base64Data?: string
  mimeType?: string
  uploading: boolean
  uploaded?: { url: string; name: string; size: number; type: 'image' | 'file' }
  error?: string
}

const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.txt', '.md', '.csv']
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp'])
const AUDIO_VIDEO_EXTENSIONS = new Set(['.mp3', '.wav', '.ogg', '.mp4'])
const MULTIMODAL_EXTENSIONS = [...ALLOWED_EXTENSIONS, '.mp3', '.wav', '.ogg', '.mp4']
const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_VIDEO_SIZE = 50 * 1024 * 1024

interface ChatInputProps {
  onSend: (content: string, attachments: FileAttachment[]) => void | Promise<void>
  isLoading: boolean
  streamingAssistantId: string | null
  onAbort: () => void
  aborting?: boolean
  selectedProvider?: string
  selectedModel?: string
  onDiaryCommand?: () => void
  editContent?: string
  focusTrigger?: number
}

function getFileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

function fileToBase64(file: File): Promise<{ data: string; mimeType: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // 提取纯 base64（去掉 data:xxx;base64, 前缀）
      const base64 = result.split(',')[1] || result
      resolve({ data: base64, mimeType: file.type })
    }
    reader.onerror = () => reject(new Error(i18nT('chat.file.readFailed')))
    reader.readAsDataURL(file)
  })
}

export function ChatInput({ onSend, isLoading, streamingAssistantId, onAbort, aborting, onDiaryCommand, editContent, focusTrigger }: ChatInputProps) {
  const { t } = useI18nStore()
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    return () => {
      attachments.forEach(a => { if (a.preview) URL.revokeObjectURL(a.preview) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (editContent) {
      setInput(editContent)
    }
  }, [editContent])

  useEffect(() => {
    if (focusTrigger !== undefined && focusTrigger > 0) {
      textareaRef.current?.focus()
    }
  }, [focusTrigger])

  const addAttachments = useCallback((files: File[]) => {
    const newAttachments: FileAttachment[] = []
    for (const file of files) {
      const ext = getFileExtension(file.name)
      if (!MULTIMODAL_EXTENSIONS.includes(ext)) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_input', action: 'attach', status: 'failure', message: `unsupported file type: ${ext}` })
        continue
      }
      const isVideo = ext === '.mp4'
      const maxSize = isVideo ? MAX_VIDEO_SIZE : MAX_FILE_SIZE
      if (file.size > maxSize) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_input', action: 'attach', status: 'failure', message: `file too large: ${file.name}` })
        continue
      }
      const attachment: FileAttachment = {
        id: crypto.randomUUID(),
        file,
        uploading: false,
      }
      if (IMAGE_EXTENSIONS.has(ext)) {
        attachment.preview = URL.createObjectURL(file)
      }
      newAttachments.push(attachment)
    }
    if (newAttachments.length > 0) {
      setAttachments(prev => [...prev, ...newAttachments])
    }
  }, [])

  const removeAttachment = useCallback((id: string) => {
    setAttachments(prev => {
      const removed = prev.find(a => a.id === id)
      if (removed?.preview) URL.revokeObjectURL(removed.preview)
      return prev.filter(a => a.id !== id)
    })
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) addAttachments(files)
  }, [addAttachments])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length > 0) {
      addAttachments(files)
    }
  }, [addAttachments])

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) addAttachments(files)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [addAttachments])

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  const handleSend = async () => {
    const trimmed = input.trim()
    if ((!trimmed && attachments.length === 0) || isLoading) return

    // 魔法命令检测：以 / 开头且不包含空格的消息视为魔法命令
    if (trimmed.startsWith('/')) {
      const parts = trimmed.split(/\s+/)
      const cmdName = parts[0].slice(1).toLowerCase()
      // /diary 保持原有处理逻辑
      if (cmdName === 'diary') {
        setInput('')
        onDiaryCommand?.()
        return
      }
      // 其他魔法命令直接发送给后端处理（agent 管道已支持魔法命令检测）
      // 注：/compact、/new、/clear、/stop、/make-skill、/make-plan 等由后端 agent 处理
    }

    if (!trimmed) return

    const userMessage = input.trim()
    const currentAttachments = attachments

    // 将图片/音频/视频附件编码为 base64，用于多模态 API 调用
    const attachmentsWithBase64: FileAttachment[] = []
    for (const att of currentAttachments) {
      const ext = getFileExtension(att.file.name)
      if (IMAGE_EXTENSIONS.has(ext) || AUDIO_VIDEO_EXTENSIONS.has(ext)) {
        try {
          const { data, mimeType } = await fileToBase64(att.file)
          attachmentsWithBase64.push({ ...att, base64Data: data, mimeType })
        } catch {
          appLogger.warning({ event: 'base64_encode_failed', module: 'chat_input', message: `failed to encode: ${att.file.name}` })
        }
      } else {
        attachmentsWithBase64.push(att)
      }
    }

    setInput('')
    // 清理 Blob URL 避免内存泄漏
    attachments.forEach(a => { if (a.preview) URL.revokeObjectURL(a.preview) })
    setAttachments([])
    await onSend(userMessage, attachmentsWithBase64)
  }

  return (
    <div
      className={`${styles['chat-input-container']} ${isDragOver ? styles['drag-over'] : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {attachments.length > 0 && (
        <div className={styles['attachments-preview']}>
          {attachments.map(att => (
            <div key={att.id} className={styles['attachment-item']}>
              {att.preview ? (
                <img src={att.preview} alt={att.file.name} className={styles['attachment-thumb']} />
              ) : (
                <div className={styles['attachment-file-icon']}>
                  <span>{getFileExtension(att.file.name).slice(1).toUpperCase()}</span>
                </div>
              )}
              {att.uploading && <div className={styles['attachment-uploading']} />}
              {att.error && <div className={styles['attachment-error']} title={att.error}>!</div>}
              <button
                className={styles['attachment-remove']}
                onClick={() => removeAttachment(att.id)}
                title="remove attachment"
              >
                <X size={10} strokeWidth={2.5} />
              </button>
              <span className={styles['attachment-name']}>{att.file.name}</span>
            </div>
          ))}
        </div>
      )}
      <div className={styles['input-row']}>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={handleFileInputChange}
          style={{ display: 'none' }}
        />
        <button
          className={styles['attach-btn']}
          onClick={() => fileInputRef.current?.click()}
          title="attach file"
          disabled={isLoading}
        >
          <Paperclip size={20} strokeWidth={2} />
        </button>
        <textarea
          ref={textareaRef}
          className={styles['chat-input']}
          placeholder="type your question... (try /diary for daily diary)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          onPaste={handlePaste}
          rows={1}
        />
        {streamingAssistantId ? (
          <button
            className={`btn ${styles['stop-btn']}`}
            onClick={onAbort}
            disabled={aborting}
            title={aborting ? t('chat.stopping') : t('chat.stopGeneration')}
          >
            <Square size={18} />
          </button>
        ) : (
          <button
            className={`btn btn-primary ${styles['send-btn']}`}
            onClick={() => void handleSend()}
            disabled={(!input.trim() && attachments.length === 0) || isLoading}
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  )
}
