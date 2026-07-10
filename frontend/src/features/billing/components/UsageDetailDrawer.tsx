/**
 * 用量明细详情抽屉组件。
 *
 * 展示单次 LLM 调用的完整计费明细，包括：
 * - 基本信息：provider / model / 创建时间 / 持续时间
 * - Token 明细：input / output / cache_read / cache_write / thoughts / total
 * - 成本分解：input_cost / output_cost / cache_read_cost / cache_write_cost / total_cost
 * - 计数方法：method + estimated 标记（估算 / 精确）
 * - extra_data：JSON 格式化展示
 *
 * 抽屉从右侧滑入，支持 ESC 关闭与遮罩点击关闭。
 */
import { useEffect, useCallback, useRef } from 'react'
import { X } from 'lucide-react'
import type { UsageRecord } from '@/features/billing/billingApi'
import styles from './UsageDetailDrawer.module.css'

interface UsageDetailDrawerProps {
  /** 当前选中的用量记录，null 时不渲染内容 */
  record: UsageRecord | null
  /** 是否打开 */
  open: boolean
  /** 关闭回调 */
  onClose: () => void
}

/** 计数方法中文标签映射 */
const METHOD_LABELS: Record<NonNullable<UsageRecord['method']>, string> = {
  api_usage: 'API',
  stream: '流式',
  tiktoken: 'tiktoken',
  ratio: '字符比率',
}

/** 可聚焦元素选择器，用于焦点陷阱 */
const FOCUSABLE_SELECTORS = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/** 格式化 token 数量，0 显示为 "-" */
function formatTokens(tokens: number | undefined): string {
  if (tokens === undefined || tokens === null || tokens === 0) return '-'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(2)}M`
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`
  return tokens.toString()
}

/** 格式化成本，保留 6 位小数 */
function formatCost(cost: number | undefined, currency: string): string {
  if (cost === undefined || cost === null) return '-'
  const symbol = currency === 'CNY' ? '¥' : '$'
  return `${symbol}${cost.toFixed(6)}`
}

/** 安全地格式化 JSON 数据 */
function formatExtraData(extra: Record<string, unknown> | undefined): string {
  if (!extra) return ''
  try {
    return JSON.stringify(extra, null, 2)
  } catch {
    return String(extra)
  }
}

function UsageDetailDrawer({ record, open, onClose }: UsageDetailDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  /** ESC 关闭与 Tab 焦点陷阱 */
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key === 'Tab' && drawerRef.current) {
        const focusableElements = Array.from(
          drawerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS)
        )
        if (focusableElements.length === 0) return
        const firstElement = focusableElements[0]
        const lastElement = focusableElements[focusableElements.length - 1]
        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault()
            lastElement.focus()
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault()
            firstElement.focus()
          }
        }
      }
    },
    [onClose]
  )

  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
      setTimeout(() => {
        const focusable = drawerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS)
        if (focusable && focusable.length > 0) {
          focusable[0].focus()
        }
      }, 0)
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
      if (previousFocusRef.current) {
        previousFocusRef.current.focus()
        previousFocusRef.current = null
      }
    }
  }, [open, handleKeyDown])

  if (!open) return null

  const currency = record?.currency || 'USD'
  const totalTokens = record
    ? (record.input_tokens || 0) +
      (record.output_tokens || 0) +
      (record.cache_read_tokens || 0) +
      (record.cache_write_tokens || 0) +
      (record.thoughts_tokens || 0)
    : 0
  const cacheReadCost = record?.cache_read_cost ?? 0
  const cacheWriteCost = record?.cache_write_cost ?? 0
  const cacheTotalCost = cacheReadCost + cacheWriteCost
  const extraDataText = record ? formatExtraData(record.extra_data) : ''
  const methodLabel = record?.method ? METHOD_LABELS[record.method] : '-'

  return (
    <div className={styles.overlay} onClick={onClose} role="presentation">
      <div
        ref={drawerRef}
        className={styles.drawer}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="用量调用详情"
      >
        <div className={styles.header}>
          <h2 className={styles.title}>用量调用详情</h2>
          <button className={styles.closeBtn} onClick={onClose} aria-label="关闭" type="button">
            <X size={18} />
          </button>
        </div>
        <div className={styles.body}>
          {!record ? (
            <p className={styles.empty}>暂无数据</p>
          ) : (
          <>
            {/* 基本信息 */}
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>基本信息</h3>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>厂商</span>
                <span className={styles.detailValue}>{record.provider}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>模型</span>
                <span className={styles.detailValue}>{record.model}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>内容类型</span>
                <span className={styles.detailValue}>{record.content_type}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>创建时间</span>
                <span className={styles.detailValue}>
                  {record.created_at ? new Date(record.created_at).toLocaleString('zh-CN') : '-'}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>持续时间</span>
                <span className={styles.detailValue}>
                  {record.duration_ms ? `${record.duration_ms} ms` : '-'}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>调用 ID</span>
                <span className={`${styles.detailValue} ${styles.mono}`}>{record.call_id}</span>
              </div>
            </section>

            {/* Token 明细 */}
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>Token 明细</h3>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>输入 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(record.input_tokens)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>输出 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(record.output_tokens)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存读取 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(record.cache_read_tokens)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存写入 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(record.cache_write_tokens)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>思考 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(record.thoughts_tokens)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>合计 Tokens</span>
                <span className={styles.detailValue}>{formatTokens(totalTokens)}</span>
              </div>
            </section>

            {/* 成本分解 */}
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>成本分解</h3>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>输入成本</span>
                <span className={styles.detailValue}>{formatCost(record.input_cost, currency)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>输出成本</span>
                <span className={styles.detailValue}>{formatCost(record.output_cost, currency)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存读取成本</span>
                <span className={styles.detailValue}>{formatCost(record.cache_read_cost, currency)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存写入成本</span>
                <span className={styles.detailValue}>{formatCost(record.cache_write_cost, currency)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存成本合计</span>
                <span className={styles.detailValue}>{formatCost(cacheTotalCost, currency)}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>总成本</span>
                <span className={styles.detailValue}>{formatCost(record.total_cost, currency)}</span>
              </div>
            </section>

            {/* 计数方法 */}
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>计数方法</h3>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>方法</span>
                <span className={styles.methodTag}>{methodLabel}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>精度</span>
                {record.estimated === undefined ? (
                  <span className={`${styles.detailValue} ${styles.muted}`}>-</span>
                ) : record.estimated ? (
                  <span className={`${styles.badge} ${styles.estimated}`}>估算</span>
                ) : (
                  <span className={`${styles.badge} ${styles.exact}`}>精确</span>
                )}
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>缓存命中</span>
                <span className={styles.detailValue}>{record.cache_hit ? '是' : '否'}</span>
              </div>
            </section>

            {/* 附加数据 */}
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>附加数据 (extra_data)</h3>
              {extraDataText ? (
                <pre className={styles.extraData}>{extraDataText}</pre>
              ) : (
                <p className={styles.empty}>暂无附加数据</p>
              )}
            </section>
          </>
          )}
        </div>
      </div>
    </div>
  )
}

export default UsageDetailDrawer
