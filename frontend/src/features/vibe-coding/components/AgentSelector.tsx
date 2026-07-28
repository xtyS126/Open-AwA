/**
 * Agent 选择器组件。
 * 下拉选择可用的 vibe coding agent，标注不可用状态。
 */
import { useI18nStore } from '@/i18n'
import type { AcpAgent } from '@/shared/api/acpApi'

export interface AgentSelectorProps {
  /** 可选 Agent 列表 */
  agents: AcpAgent[]
  /** 当前选中的 Agent ID */
  value: string
  /** 选择变更回调 */
  onChange: (id: string) => void
}

/** Agent 选择器 —— 下拉列表，不可用 Agent 禁用并标注 */
export default function AgentSelector({ agents, value, onChange }: AgentSelectorProps) {
  const { t } = useI18nStore()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <label
        htmlFor="vibe-agent-select"
        style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}
      >
        {t('vibeCoding.selectAgent')}
      </label>
      <select
        id="vibe-agent-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          height: '34px',
          padding: '0 10px',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-bg-secondary)',
          color: 'var(--color-text)',
          fontSize: 'var(--text-sm)',
          cursor: 'pointer',
        }}
      >
        <option value="">{t('vibeCoding.selectAgent')}</option>
        {agents.map((agent) => {
          const canInstallLocally = agent.id === 'opencode'
          const selectable = agent.available || canInstallLocally
          const status = agent.available
            ? ''
            : canInstallLocally
              ? '（可在项目中安装）'
              : ` (${t('vibeCoding.unavailable')})`
          return (
            <option
              key={agent.id}
              value={agent.id}
              disabled={!selectable}
            >
              {agent.name}{status}
            </option>
          )
        })}
      </select>
    </div>
  )
}
