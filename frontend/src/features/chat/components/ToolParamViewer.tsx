import { useState, useCallback } from 'react'
import styles from './ToolParamViewer.module.css'

interface ToolParamViewerProps {
  data: unknown
  label: string
  defaultExpanded?: boolean
}

const MAX_STRING_LENGTH = 200
const DEFAULT_COLLAPSE_DEPTH = 2

function JsonNode({
  value,
  depth,
  keyName,
}: {
  value: unknown
  depth: number
  keyName?: string
}) {
  const [expanded, setExpanded] = useState(depth < DEFAULT_COLLAPSE_DEPTH)
  const [stringExpanded, setStringExpanded] = useState(false)

  if (value === null) {
    return <span className={styles['json-null']}>null</span>
  }

  if (typeof value === 'boolean') {
    return <span className={styles['json-boolean']}>{String(value)}</span>
  }

  if (typeof value === 'number') {
    return <span className={styles['json-number']}>{String(value)}</span>
  }

  if (typeof value === 'string') {
    const truncated = !stringExpanded && value.length > MAX_STRING_LENGTH
    const display = truncated ? value.slice(0, MAX_STRING_LENGTH) + '...' : value
    return (
      <span className={styles['json-string']}>
        "{display}"
        {truncated && (
          <button
            type="button"
            className={styles['expand-string-btn']}
            onClick={() => setStringExpanded(true)}
          >
            展开
          </button>
        )}
      </span>
    )
  }

  if (Array.isArray(value)) {
    const toggle = () => setExpanded((prev) => !prev)
    return (
      <span className={styles['json-array']}>
        <button type="button" className={styles['toggle-btn']} onClick={toggle}>
          {expanded ? '▾' : '▸'}
        </button>
        {keyName && <span className={styles['json-key']}>{keyName}: </span>}
        <span className={styles['json-bracket']}>[</span>
        {expanded ? (
          <span className={styles['json-children']}>
            {value.map((item, index) => (
              <span key={index} className={styles['json-child']}>
                <JsonNode value={item} depth={depth + 1} />
                {index < value.length - 1 && <span className={styles['json-comma']}>,</span>}
              </span>
            ))}
          </span>
        ) : (
          <span className={styles['json-ellipsis']}>
            {value.length > 0 ? ` ${value.length} 项 ` : ''}
          </span>
        )}
        <span className={styles['json-bracket']}>]</span>
      </span>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    const toggle = () => setExpanded((prev) => !prev)
    return (
      <span className={styles['json-object']}>
        <button type="button" className={styles['toggle-btn']} onClick={toggle}>
          {expanded ? '▾' : '▸'}
        </button>
        {keyName && <span className={styles['json-key']}>{keyName}: </span>}
        <span className={styles['json-bracket']}>{'{'}</span>
        {expanded ? (
          <span className={styles['json-children']}>
            {entries.map(([k, v], index) => (
              <span key={k} className={styles['json-child']}>
                <JsonNode value={v} depth={depth + 1} keyName={k} />
                {index < entries.length - 1 && <span className={styles['json-comma']}>,</span>}
              </span>
            ))}
          </span>
        ) : (
          <span className={styles['json-ellipsis']}>
            {entries.length > 0 ? ` ${entries.length} 个字段 ` : ''}
          </span>
        )}
        <span className={styles['json-bracket']}>{'}'}</span>
      </span>
    )
  }

  return <span className={styles['json-unknown']}>{String(value)}</span>
}

export function ToolParamViewer({ data, label, defaultExpanded = false }: ToolParamViewerProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const handleCopy = useCallback(async () => {
    try {
      const text = JSON.stringify(data, null, 2)
      await navigator.clipboard.writeText(text)
    } catch {
      // 剪贴板不可用时静默失败
    }
  }, [data])

  return (
    <div className={styles['container']}>
      <button
        type="button"
        className={styles['header']}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <span className={`${styles['chevron']} ${expanded ? styles['expanded'] : ''}`}>▶</span>
        <span className={styles['label']}>{label}</span>
        <button
          type="button"
          className={styles['copy-btn']}
          onClick={(e) => {
            e.stopPropagation()
            void handleCopy()
          }}
          title="复制到剪贴板"
        >
          复制
        </button>
      </button>
      {expanded && (
        <div className={styles['body']}>
          <pre className={styles['code']}>
            <code>
              <JsonNode value={data} depth={0} />
            </code>
          </pre>
        </div>
      )}
    </div>
  )
}

export default ToolParamViewer
