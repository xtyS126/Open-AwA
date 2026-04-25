import { useState, useRef, useCallback, useEffect } from 'react'
import { X, Paperclip, Send, Square } from 'lucide-react'
import { chatAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from '../ChatPage.module.css'

export interface FileAttachment {
  id: string
  file: File
  preview?: string
  uploading: boolean
  uploaded?: { url: string; name: string; size: number; type: 'image' | 'file' }
  error?: string
}

const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.txt', '.md', '.csv']
const MAX_FILE_SIZE = 10 * 1024 * 1024
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp'])

interface ChatInputProps {
  onSend: (content: string, attachments: FileAttachment[]) => void | Promise<void>
  isLoading: boolean
  streamingAssistantId: string | null
  onAbort: () => void
}

function getFileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

export function ChatInput({ onSend, isLoading, streamingAssistantId, onAbort }: ChatInputProps) {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    return () => {
      attachments.forEach(a => { if (a.preview) URL.revokeObjectURL(a.preview) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addAttachments = useCallback((files: File[]) => {
    const newAttachments: FileAttachment[] = []
    for (const file of files) {
      const ext = getFileExtension(file.name)
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_input', action: 'attach', status: 'failure', message: `unsupported file type: ${ext}` })
        continue
      }
      if (file.size > MAX_FILE_SIZE) {
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

  const uploadAttachments = useCallback(async (items: FileAttachment[]): Promise<FileAttachment[]> => {
    const results: FileAttachment[] = []
    for (const item of items) {
      setAttachments(prev => prev.map(a => a.id === item.id ? { ...a, uploading: true } : a))
      try {
        const res = await chatAPI.upload(item.file)
        const data = res.data
        const uploaded = { ...item, uploading: false, uploaded: { url: data.url, name: data.original_name, size: data.size, type: data.type as 'image' | 'file' } }
        setAttachments(prev => prev.map(a => a.id === item.id ? uploaded : a))
        results.push(uploaded)
      } catch {
        setAttachments(prev => prev.map(a => a.id === item.id ? { ...a, uploading: false, error: 'upload failed' } : a))
      }
    }
    return results
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
    if ((!input.trim() && attachments.length === 0) || isLoading) return

    const userMessage = input.trim()
    const currentAttachments = attachments

    const pendingUploads = currentAttachments.filter(a => !a.uploaded && !a.error)
    let uploadedAttachments: FileAttachment[] = []
    if (pendingUploads.length > 0) {
      uploadedAttachments = await uploadAttachments(pendingUploads)
    } else {
      uploadedAttachments = currentAttachments.filter(a => a.uploaded)
    }

    setInput('')
    setAttachments([])
    await onSend(userMessage, uploadedAttachments)
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
          className={styles['chat-input']}
          placeholder="type your question..."
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
            title="stop generating"
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
