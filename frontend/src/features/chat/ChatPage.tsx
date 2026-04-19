import { useState, useRef, useEffect, useCallback } from 'react'
import { X, Paperclip } from 'lucide-react'
import { chatAPI } from '@/shared/api/api'
import { useChatStore } from '@/features/chat/store/chatStore'
import { appLogger } from '@/shared/utils/logger'
import { ReasoningContent } from './components/ReasoningContent'
import { MessageContent } from './components/MessageContent'
import styles from './ChatPage.module.css'

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/* 附件类型 */
interface FileAttachment {
  id: string
  file: File
  preview?: string   // 图片 blob URL
  uploading: boolean
  uploaded?: { url: string; name: string; size: number; type: 'image' | 'file' }
  error?: string
}

const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.txt', '.md', '.csv']
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp'])

function ChatPage() {
  const [input, setInput] = useState('')
  const { messages, addMessage, updateLastMessage, setLoading, isLoading, clearMessages, sessionId, outputMode, setOutputMode, selectedModel, setMessages } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const isMountedRef = useRef(true)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [isDragOver, setIsDragOver] = useState(false)

  // Buffer references for background throttling
  const bufferRef = useRef({
    content: '',
    reasoning: '',
    lastUpdateTime: Date.now()
  })

  const flushBuffer = useCallback(() => {
    if (bufferRef.current.content || bufferRef.current.reasoning) {
      updateLastMessage(bufferRef.current.content, bufferRef.current.reasoning)
      bufferRef.current.content = ''
      bufferRef.current.reasoning = ''
      bufferRef.current.lastUpdateTime = Date.now()
    }
  }, [updateLastMessage])

  const scrollToBottom = useCallback(() => {
    if (document.hidden) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      activeAbortControllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        flushBuffer()
        // Adding a slight delay to ensure DOM is updated before scrolling
        setTimeout(scrollToBottom, 50)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [flushBuffer, scrollToBottom])

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
  }, [])

  // 页面挂载或会话切换时加载历史消息
  useEffect(() => {
    if (!sessionId || sessionId === 'default') return
    let cancelled = false
    const loadHistory = async () => {
      try {
        const response = await chatAPI.getHistory(sessionId)
        if (cancelled) return
        const history = response.data
        if (Array.isArray(history) && history.length > 0) {
          const restored = history.map((msg: { id: string; role: string; content: string; timestamp: string }) => ({
            id: msg.id?.toString() || crypto.randomUUID(),
            role: msg.role as 'user' | 'assistant',
            content: msg.content,
            timestamp: new Date(msg.timestamp),
          }))
          setMessages(restored)
          appLogger.info({
            event: 'chat_history_loaded',
            module: 'chat_page',
            action: 'load_history',
            status: 'success',
            message: `loaded ${restored.length} history messages`,
          })
        }
      } catch {
        // 历史加载失败不阻塞用户操作
        appLogger.warning({
          event: 'chat_history_load_failed',
          module: 'chat_page',
          action: 'load_history',
          status: 'failure',
          message: 'failed to load chat history',
        })
      }
    }
    loadHistory()
    return () => { cancelled = true }
  }, [sessionId, setMessages])

  /* ---- 附件处理 ---- */

  const getFileExtension = (name: string) => {
    const dot = name.lastIndexOf('.')
    return dot >= 0 ? name.slice(dot).toLowerCase() : ''
  }

  const addAttachments = useCallback((files: File[]) => {
    const newAttachments: FileAttachment[] = []
    for (const file of files) {
      const ext = getFileExtension(file.name)
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_page', action: 'attach', status: 'failure', message: `不支持的文件类型: ${ext}` })
        continue
      }
      if (file.size > MAX_FILE_SIZE) {
        appLogger.warning({ event: 'file_rejected', module: 'chat_page', action: 'attach', status: 'failure', message: `文件过大: ${file.name}` })
        continue
      }
      const attachment: FileAttachment = {
        id: crypto.randomUUID(),
        file,
        uploading: false,
      }
      // 图片创建预览 URL
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
        setAttachments(prev => prev.map(a => a.id === item.id ? { ...a, uploading: false, error: '上传失败' } : a))
      }
    }
    return results
  }, [])

  /* 拖拽事件 */
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

  /* 粘贴图片 */
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length > 0) {
      addAttachments(files)
    }
  }, [addAttachments])

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) addAttachments(files)
    // 重置 input 以允许选择相同文件
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [addAttachments])

  /* 清理附件预览 URL */
  useEffect(() => {
    return () => {
      attachments.forEach(a => { if (a.preview) URL.revokeObjectURL(a.preview) })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const parseSelectedModel = (value: string): { provider?: string; model?: string } => {
    if (!value) {
      return { provider: undefined, model: undefined }
    }

    const separatorIndex = value.indexOf(':')
    if (separatorIndex <= 0 || separatorIndex >= value.length - 1) {
      return { provider: undefined, model: undefined }
    }

    return {
      provider: value.slice(0, separatorIndex),
      model: value.slice(separatorIndex + 1)
    }
  }

  const handleSend = async () => {
    if ((!input.trim() && attachments.length === 0) || isLoading) return

    const userMessage = input.trim()
    const requestId = activeRequestIdRef.current + 1
    activeRequestIdRef.current = requestId
    activeAbortControllerRef.current?.abort()
    const abortController = new AbortController()
    activeAbortControllerRef.current = abortController
    let streamErrorHandled = false

    // 先上传待上传的附件
    let uploadedAttachments: FileAttachment[] = []
    const pendingUploads = attachments.filter(a => !a.uploaded && !a.error)
    if (pendingUploads.length > 0) {
      uploadedAttachments = await uploadAttachments(pendingUploads)
    } else {
      uploadedAttachments = attachments.filter(a => a.uploaded)
    }

    // 构造消息文本（附件信息附加到消息末尾）
    let fullMessage = userMessage
    if (uploadedAttachments.length > 0) {
      const fileRefs = uploadedAttachments
        .filter(a => a.uploaded)
        .map(a => `[附件: ${a.uploaded!.name}](${a.uploaded!.url})`)
        .join('\n')
      if (fileRefs) {
        fullMessage = fullMessage ? `${fullMessage}\n\n${fileRefs}` : fileRefs
      }
    }

    if (!fullMessage) return

    appLogger.info({
      event: 'chat_send',
      module: 'chat_page',
      action: 'send_message',
      status: 'start',
      message: 'chat send started',
      extra: { session_id: sessionId, input_length: fullMessage.length, mode: outputMode, attachments: uploadedAttachments.length },
    })
    setInput('')
    setAttachments([])
    addMessage('user', fullMessage)
    setLoading(true)

    try {
      const { provider, model } = parseSelectedModel(selectedModel)

      if (outputMode === 'stream') {
        let isFirstChunk = true
        bufferRef.current = { content: '', reasoning: '', lastUpdateTime: Date.now() }

        await chatAPI.sendMessageStream(
          fullMessage,
          sessionId,
          provider,
          model,
          (content, reasoning) => {
            if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
              return
            }
            if (isFirstChunk) {
              setLoading(false)
              addMessage('assistant', content, reasoning)
              isFirstChunk = false
              bufferRef.current.lastUpdateTime = Date.now()
            } else {
              if (document.hidden) {
                // Background mode: throttle updates to prevent massive DOM manipulation
                bufferRef.current.content += content
                bufferRef.current.reasoning += reasoning
                const now = Date.now()
                if (now - bufferRef.current.lastUpdateTime > 1000) {
                  flushBuffer()
                }
              } else {
                // Foreground mode: instant update
                // If there's any remaining buffer, flush it with the new chunk
                if (bufferRef.current.content || bufferRef.current.reasoning) {
                  updateLastMessage(
                    bufferRef.current.content + content,
                    bufferRef.current.reasoning + reasoning
                  )
                  bufferRef.current.content = ''
                  bufferRef.current.reasoning = ''
                  bufferRef.current.lastUpdateTime = Date.now()
                } else {
                  updateLastMessage(content, reasoning)
                }
              }
            }
          },
          (error) => {
            if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
              return
            }
            streamErrorHandled = true
            flushBuffer()
            appLogger.error({
              event: 'chat_stream_error',
              module: 'chat_page',
              action: 'receive_stream',
              status: 'failure',
              message: 'chat stream error',
              extra: { error: error instanceof Error ? error.message : String(error) },
            })
            if (isFirstChunk) {
              setLoading(false)
              addMessage('assistant', `请求失败：${sanitizeDisplayedError(error.message)}`)
              isFirstChunk = false
            } else {
              updateLastMessage(`\n\n[流中断：${sanitizeDisplayedError(error.message)}]`)
            }
          },
          { signal: abortController.signal }
        )
        // Stream completed successfully, flush any remaining buffered data
        flushBuffer()

        if (!isMountedRef.current || activeRequestIdRef.current !== requestId || streamErrorHandled) {
          return
        }
      } else {
        const response = await chatAPI.sendMessage(fullMessage, sessionId, provider, model, 'direct', {
          signal: abortController.signal,
        })
        if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
          return
        }
        const assistantText = response.data.response
        const backendError = response.data.error
        const reasoningContent = response.data.reasoning_content

        if (assistantText && assistantText.trim()) {
          addMessage('assistant', assistantText, reasoningContent || undefined)
        } else if (backendError?.message) {
          addMessage('assistant', `请求失败：${sanitizeDisplayedError(backendError.message)}`)
        } else {
          addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。')
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      appLogger.error({
        event: 'chat_send',
        module: 'chat_page',
        action: 'send_message',
        status: 'failure',
        message: 'chat send failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      if (isMountedRef.current && activeRequestIdRef.current === requestId && !streamErrorHandled) {
        addMessage('assistant', '抱歉，发生了错误。请稍后重试。')
      }
    } finally {
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setLoading(false)
      }
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className={styles['chat-page']}>
      <div className={styles['chat-header']}>
        <h1>AI 助手</h1>
        <div className={styles['header-controls']}>
          <select
            value={outputMode}
            onChange={(e) => setOutputMode(e.target.value as 'stream' | 'direct')}
            className={styles['mode-select']}
          >
            <option value="stream">流式传输</option>
            <option value="direct">直接输出</option>
          </select>
          {selectedModel && (
            <span className={styles['current-model']}>{selectedModel.split(':').pop()}</span>
          )}
        </div>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={clearMessages}>
          新对话
        </button>
      </div>

      <div
        className={`${styles['chat-messages']} ${isDragOver ? styles['drag-over'] : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {messages.length === 0 && (
          <div className={styles['chat-empty']}>
            <p>你好！有什么可以帮助你的吗？</p>
          </div>
        )}

        {messages.map((message, index) => {
          const isLastMessage = index === messages.length - 1
          const isCurrentlyStreaming = isLoading && isLastMessage && message.role === 'assistant'
          
          return (
            <div
              key={message.id}
              className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}
            >
              <div className={styles['message-content']}>
                {message.reasoning_content && (
                  <ReasoningContent 
                    messageId={message.id}
                    content={message.reasoning_content}
                    isStreaming={isCurrentlyStreaming}
                  />
                )}
                <MessageContent content={message.content} role={message.role} />
              </div>
            </div>
          )
        })}

        {isLoading && (
          <div className={`${styles['message']} ${styles['assistant']}`}>
            <div className={styles['message-content']}>
              <p className={styles['loading-text']}>思考中...</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className={styles['chat-input-container']}>
        {/* 附件预览栏 */}
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
                  title="移除附件"
                >
                  <X size={10} strokeWidth={2.5} />
                </button>
                <span className={styles['attachment-name']}>{att.file.name}</span>
              </div>
            ))}
          </div>
        )}
        <div className={styles['input-row']}>
          {/* 附件按钮 */}
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
            title="添加附件"
            disabled={isLoading}
          >
            <Paperclip size={20} strokeWidth={2} />
          </button>
          <textarea
            className={styles['chat-input']}
            placeholder="输入你的问题..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            onPaste={handlePaste}
            rows={1}
          />
          <button
            className={`btn btn-primary ${styles['send-btn']}`}
            onClick={handleSend}
            disabled={(!input.trim() && attachments.length === 0) || isLoading}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}

export default ChatPage
