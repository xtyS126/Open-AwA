import { useEffect, useState } from 'react'
import { CheckCircle2, HelpCircle, Loader2, Send } from 'lucide-react'
import { chatAPI } from '@/shared/api/api'
import type { AskUserRequest } from '@/features/chat/types'
import styles from './AskUserCard.module.css'

interface AskUserCardProps {
  /** 当前挂起的 ask_user 请求（为 null 时不渲染） */
  request: AskUserRequest | null
  /** 提交回答后的回调（用于清空 state 或刷新 UI） */
  onResolved?: () => void
}

type SubmitStatus = 'idle' | 'submitting' | 'done' | 'error'

/**
 * AskUserCard 组件：渲染 AI 主动提问的问题卡片。
 *
 * 接收后端下发的 ask_user 事件载荷，支持：
 * - 单选 / 多选预设选项
 * - 自由文本输入
 * - 提交后调用 POST /api/chat/ask-user/reply
 *
 * 同一时刻只渲染一个 ask_user 请求（后端 ask_user 工具 is_concurrency_safe=False）。
 */
export function AskUserCard({ request, onResolved }: AskUserCardProps) {
  const [selectedOptions, setSelectedOptions] = useState<string[]>([])
  const [freeText, setFreeText] = useState<string>('')
  const [status, setStatus] = useState<SubmitStatus>('idle')
  const [errorMsg, setErrorMsg] = useState<string>('')

  // 切换问题时重置内部状态（新问题到达时清空选项/文本/状态）
  useEffect(() => {
    setSelectedOptions([])
    setFreeText('')
    setStatus('idle')
    setErrorMsg('')
  }, [request?.request_id])

  if (request === null) return null

  const toggleOption = (option: string) => {
    if (request.allow_multiple) {
      setSelectedOptions((prev) =>
        prev.includes(option) ? prev.filter((o) => o !== option) : [...prev, option],
      )
    } else {
      setSelectedOptions([option])
    }
  }

  const canSubmit = (): boolean => {
    if (status === 'submitting' || status === 'done') return false
    if (request.options.length > 0 && selectedOptions.length === 0 && !request.allow_free_text) {
      return false
    }
    if (request.options.length === 0 && !freeText.trim()) {
      return false
    }
    return true
  }

  const handleSubmit = async () => {
    if (!canSubmit()) return
    setStatus('submitting')
    setErrorMsg('')
    try {
      await chatAPI.replyAskUser({
        request_id: request.request_id,
        session_id: request.session_id,
        answer: freeText.trim(),
        selected_options: selectedOptions,
      })
      setStatus('done')
      onResolved?.()
    } catch (e) {
      setStatus('error')
      setErrorMsg(e instanceof Error ? e.message : '提交失败')
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <HelpCircle size={16} />
        <span className={styles.title}>AI 需要你的补充信息</span>
      </div>

      <div className={styles.question}>{request.question}</div>

      {request.options.length > 0 && (
        <div className={styles.options} role={request.allow_multiple ? 'group' : 'radiogroup'}>
          {request.options.map((option) => {
            const selected = selectedOptions.includes(option)
            return (
              <button
                key={option}
                type="button"
                className={`${styles.option} ${selected ? styles.optionSelected : ''}`}
                onClick={() => toggleOption(option)}
                disabled={status === 'done'}
                aria-pressed={selected}
              >
                {request.allow_multiple ? (
                  <CheckCircle2 size={16} className={styles.optionCheckbox} />
                ) : (
                  <span className={styles.optionRadio}>{selected ? '●' : '○'}</span>
                )}
                <span className={styles.optionLabel}>{option}</span>
              </button>
            )
          })}
        </div>
      )}

      {request.allow_free_text && (
        <textarea
          className={styles.input}
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder={request.placeholder || '输入你的回答...'}
          aria-label={request.placeholder || '输入你的回答'}
          disabled={status === 'done'}
          rows={3}
          maxLength={10000}
        />
      )}

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleSubmit}
          disabled={!canSubmit()}
        >
          {status === 'submitting' ? (
            <Loader2 size={14} className={styles.spinner} />
          ) : (
            <Send size={14} />
          )}
          <span style={{ marginLeft: 6 }}>{status === 'done' ? '已提交' : '提交回答'}</span>
        </button>
      </div>

      {status === 'done' && (
        <div className={`${styles.statusBar} ${styles.statusDone}`}>
          <CheckCircle2 size={12} />
          <span>回答已提交，等待 AI 继续</span>
        </div>
      )}
      {status === 'error' && (
        <div className={`${styles.statusBar} ${styles.statusError}`}>
          <span>{errorMsg}</span>
        </div>
      )}
    </div>
  )
}
