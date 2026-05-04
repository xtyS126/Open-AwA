import { useState, useMemo } from 'react'
import type { TaskStepMeta, ToolEventMeta, TaskStatus } from '@/features/chat/types'
import { getTaskTitle } from '@/features/chat/utils/executionMeta'
import styles from './TaskPanel.module.css'

interface TaskPanelProps {
  steps: TaskStepMeta[]
  toolEvents: ToolEventMeta[]
  isStreaming: boolean
  onStopAgent: (agentId: string) => void
  expanded: boolean
  onToggle: () => void
}

function getKindLabel(kind: string): string {
  switch (kind) {
    case 'skill': return '技能'
    case 'plugin': return '插件'
    case 'mcp': return 'MCP'
    case 'task': return '代理'
    default: return kind
  }
}

export function TaskPanel({
  steps,
  toolEvents,
  isStreaming,
  onStopAgent,
  expanded,
  onToggle,
}: TaskPanelProps) {
  const [showCompleted, setShowCompleted] = useState(false)

  const activeItems = useMemo(() => {
    const items: { id: string; label: string; kind: string; status: TaskStatus; isStep: boolean }[] = []

    for (const step of steps) {
      if (step.status === 'running' || step.status === 'pending') {
        items.push({
          id: `step-${step.step}-${step.action}`,
          label: getTaskTitle(step),
          kind: step.action,
          status: step.status,
          isStep: true,
        })
      }
    }

    for (const tool of toolEvents) {
      if (tool.status === 'running' || tool.status === 'pending') {
        items.push({
          id: tool.id,
          label: tool.name,
          kind: tool.kind,
          status: tool.status,
          isStep: false,
        })
      }
    }

    return items
  }, [steps, toolEvents])

  const completedItems = useMemo(() => {
    const items: { id: string; label: string; kind: string; status: TaskStatus }[] = []

    for (const step of steps) {
      if (step.status === 'completed' || step.status === 'error') {
        items.push({
          id: `step-${step.step}-${step.action}`,
          label: getTaskTitle(step),
          kind: step.action,
          status: step.status,
        })
      }
    }

    for (const tool of toolEvents) {
      if (tool.status === 'completed' || tool.status === 'error') {
        items.push({
          id: tool.id,
          label: tool.name,
          kind: tool.kind,
          status: tool.status,
        })
      }
    }

    return items
  }, [steps, toolEvents])

  const statusDotClass = (status: TaskStatus) => {
    switch (status) {
      case 'completed': return styles['status-dot-completed']
      case 'running': return styles['status-dot-running']
      case 'error': return styles['status-dot-error']
      default: return styles['status-dot-pending']
    }
  }

  return (
    <div className={`${styles.panel} ${expanded ? styles.expanded : styles.collapsed}`}>
      <button
        type="button"
        className={styles['toggle-btn']}
        onClick={onToggle}
        title={expanded ? '折叠任务面板' : '展开任务面板'}
      >
        <span className={`${styles['toggle-arrow']} ${expanded ? styles['arrow-expanded'] : styles['arrow-collapsed']}`}>
          {'▶'}
        </span>
        {activeItems.length > 0 && (
          <span className={styles['toggle-badge']}>{activeItems.length}</span>
        )}
      </button>

      {expanded && (
        <div className={styles['panel-content']}>
          <div className={styles['panel-header']}>
            <span className={styles['panel-title']}>任务面板</span>
            {isStreaming && <span className={styles['streaming-indicator']} />}
          </div>

          {activeItems.length > 0 && (
            <div className={styles['section']}>
              <div className={styles['section-title']}>进行中</div>
              <div className={styles['item-list']}>
                {activeItems.map((item) => (
                  <div key={item.id} className={styles['item']}>
                    <span className={statusDotClass(item.status)} />
                    <span className={styles['item-kind']}>{getKindLabel(item.kind)}</span>
                    <span className={styles['item-label']}>{item.label}</span>
                    {!item.isStep && item.status === 'running' && (
                      <button
                        type="button"
                        className={styles['stop-btn']}
                        onClick={() => onStopAgent(item.id)}
                        title="停止"
                      >
                        x
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeItems.length === 0 && completedItems.length === 0 && (
            <div className={styles['empty-hint']}>暂无任务</div>
          )}

          {completedItems.length > 0 && (
            <div className={styles['section']}>
              <button
                type="button"
                className={styles['section-toggle']}
                onClick={() => setShowCompleted((prev) => !prev)}
              >
                <span className={`${styles['toggle-arrow']} ${showCompleted ? styles['arrow-expanded'] : styles['arrow-collapsed']}`}>
                  {'▶'}
                </span>
                <span className={styles['section-title']}>已完成 ({completedItems.length})</span>
              </button>
              {showCompleted && (
                <div className={styles['item-list']}>
                  {completedItems.map((item) => (
                    <div key={item.id} className={styles['item']}>
                      <span className={statusDotClass(item.status)} />
                      <span className={styles['item-kind']}>{getKindLabel(item.kind)}</span>
                      <span className={styles['item-label']}>{item.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
