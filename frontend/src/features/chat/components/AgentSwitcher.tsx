/**
 * Agent 切换器 — 在聊天页面中切换当前 Agent 类型。
 * 改变 Agent 类型会影响系统提示、工具可用性和对话行为。
 */
import React, { useState, useEffect } from 'react'
import { Eye, Zap, Wrench } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { subagentsApi } from '@/shared/api/subagentsApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './AgentSwitcher.module.css'

interface AgentSwitcherProps {
  currentAgent: string
  onAgentChange: (agentType: string) => void
}

const AGENT_ICONS: Record<string, LucideIcon> = {
  Explore: Eye,
  Plan: Zap,
  'general-purpose': Wrench,
}

const AGENT_LABELS: Record<string, string> = {
  Explore: '探索',
  Plan: '规划',
  'general-purpose': '通用',
}

/** Agent 切换器内部使用的 Agent 项 */
interface AgentSwitcherItem {
  name: string
  type: string
  description: string
}

const DEFAULT_AGENTS: AgentSwitcherItem[] = [
  { name: 'Explore', type: 'Explore', description: '只读代码搜索和调研' },
  { name: 'Plan', type: 'Plan', description: '仅只读规划分析' },
  { name: 'general-purpose', type: 'general-purpose', description: '完整读写能力' },
]

const AgentSwitcher: React.FC<AgentSwitcherProps> = ({ currentAgent, onAgentChange }) => {
  const [agents, setAgents] = useState<AgentSwitcherItem[]>(DEFAULT_AGENTS)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    subagentsApi.listAgents().then((data) => {
      if (!cancelled && data.agents?.length > 0) {
        // 后端 RegisteredAgent 用 name 兼容 type 字段
        setAgents(data.agents.map((a) => ({ name: a.name, type: a.name, description: a.description })))
      }
    }).catch((error) => {
      appLogger.error({ event: 'agent_list_failed', module: 'chat', message: '加载Agent列表失败', extra: { error: error instanceof Error ? error.message : String(error) } })
    })
    return () => { cancelled = true }
  }, [])

  const Icon = AGENT_ICONS[currentAgent] || Zap

  return (
    <div className={styles.switcher}>
      <button className={styles.trigger} onClick={() => setOpen(!open)} title="切换 Agent 类型">
        <Icon size={14} />
        <span className={styles.label}>{AGENT_LABELS[currentAgent] || currentAgent}</span>
        <span className={styles.arrow}>▾</span>
      </button>

      {open && (
        <>
          <div className={styles.backdrop} onClick={() => setOpen(false)} />
          <div className={styles.dropdown}>
            {agents.map((agent) => {
              const AgentIcon = AGENT_ICONS[agent.type] || Zap
              return (
                <div
                  key={agent.type}
                  className={`${styles.item} ${agent.type === currentAgent ? styles.active : ''}`}
                  onClick={() => { onAgentChange(agent.type); setOpen(false) }}
                >
                  <div className={styles.itemIcon}>
                    <AgentIcon size={16} />
                  </div>
                  <div className={styles.itemInfo}>
                    <span className={styles.itemName}>{agent.name}</span>
                    <span className={styles.itemDesc}>{agent.description}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export default React.memo(AgentSwitcher)
