/**
 * 对话消息的点赞/点踩反馈按钮。
 * 提交后锁定状态，防止重复提交。
 */
import { useState } from 'react'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import api from '@/shared/api/api'
import styles from './FeedbackButtons.module.css'

interface FeedbackButtonsProps {
  sessionId: string
  messageId: string
  roleId?: string
}

export default function FeedbackButtons({ sessionId, messageId, roleId }: FeedbackButtonsProps) {
  const [feedback, setFeedback] = useState<'positive' | 'negative' | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (type: 'positive' | 'negative') => {
    if (submitting) return
    setSubmitting(true)
    try {
      await api.post('/feedback', {
        session_id: sessionId,
        message_id: messageId,
        rating: type === 'positive' ? 1 : -1,
        feedback_type: type,
        role_id: roleId || '',
      })
      setFeedback(type)
    } catch (e) {
      console.error('提交反馈失败', e)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.container}>
      <button
        className={`${styles.btn} ${feedback === 'positive' ? styles.active : ''}`}
        onClick={() => handleSubmit('positive')}
        disabled={submitting || feedback !== null}
        title="有帮助"
      >
        <ThumbsUp size={14} />
      </button>
      <button
        className={`${styles.btn} ${feedback === 'negative' ? styles.activeNegative : ''}`}
        onClick={() => handleSubmit('negative')}
        disabled={submitting || feedback !== null}
        title="需改进"
      >
        <ThumbsDown size={14} />
      </button>
    </div>
  )
}
