/**
 * 用户画像设置组件
 * 配置 AI 自主提取画像的触发条件：
 *   - N 值阈值：达到 N 轮对话后触发自主画像提取
 *   - 探针触发条件：低置信度 / 新兴趣不确定 / 定期复核
 * 同时展示距上次提取的轮数与上次提取时间，作为只读状态信息。
 */
import { useEffect } from 'react'
import type { ProfileSettings, ProbeFlags } from '@/shared/api/profileApi'
import styles from '@/features/settings/SettingsPage.module.css'

/** 探针选项配置：key + 标题 + 说明文本 */
interface ProbeOption {
  key: keyof ProbeFlags
  label: string
  description: string
}

/** 探针触发条件复选框配置 */
const PROBE_OPTIONS: ProbeOption[] = [
  {
    key: 'low_confidence',
    label: '低置信度',
    description: '画像事实置信度低于 0.5 时生成探针让你确认',
  },
  {
    key: 'new_interest',
    label: '新兴趣不确定',
    description: '检测到新兴趣但无法归类时生成探针',
  },
  {
    key: 'periodic_review',
    label: '定期复核',
    description: '每 20 轮对话触发一次画像复核',
  },
]

/** N 值滑块范围 */
const N_THRESHOLD_MIN = 3
const N_THRESHOLD_MAX = 20

interface ProfileSettingsTabProps {
  /** 是否正在加载已保存的设置 */
  loading: boolean
  /** 已保存的设置（用于展示只读状态信息） */
  settings: ProfileSettings | null
  /** 当前编辑中的 N 值（本地草稿） */
  draftNThreshold: number
  /** 当前编辑中的探针 flags（本地草稿） */
  draftProbeFlags: ProbeFlags
  /** 是否正在保存 */
  saving: boolean
  /** 草稿与已保存值是否存在差异（用于启用/禁用保存按钮） */
  hasChanges: boolean

  /** 加载设置回调（挂载时调用） */
  onLoad: () => void
  /** 保存设置回调 */
  onSave: () => void
  /** N 值变更回调 */
  onNThresholdChange: (value: number) => void
  /** 探针 flag 变更回调 */
  onProbeFlagChange: (key: keyof ProbeFlags, value: boolean) => void
}

export function ProfileSettingsTab({
  loading,
  settings,
  draftNThreshold,
  draftProbeFlags,
  saving,
  hasChanges,
  onLoad,
  onSave,
  onNThresholdChange,
  onProbeFlagChange,
}: ProfileSettingsTabProps) {
  // 挂载时加载设置
  useEffect(() => {
    onLoad()
  }, [onLoad])

  /** 格式化上次提取时间，null 时返回占位文本 */
  const formatLastExtracted = (value: string | null): string => {
    if (!value) return '从未提取'
    try {
      return new Date(value).toLocaleString('zh-CN')
    } catch {
      return value
    }
  }

  return (
    <div className={styles['settings-section']}>
      <h2>用户画像</h2>
      <p className={styles['section-desc']}>
        配置 AI 自主提取画像的触发条件与探针
      </p>

      {loading ? (
        <div className={styles['loading']}>加载中...</div>
      ) : (
        <>
          {/* N 值滑块 */}
          <div className={styles['setting-item']}>
            <label>N 值阈值：{draftNThreshold}</label>
            <div className={styles['slider-row']}>
              <input
                type="range"
                min={N_THRESHOLD_MIN}
                max={N_THRESHOLD_MAX}
                step={1}
                value={draftNThreshold}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(next)) {
                    onNThresholdChange(next)
                  }
                }}
                className={styles['param-slider']}
                aria-label="画像提取 N 值阈值"
              />
              <span className={styles['param-hint-inline']}>
                {draftNThreshold} 轮（范围 {N_THRESHOLD_MIN}-{N_THRESHOLD_MAX}）
              </span>
            </div>
            <span className={styles['param-hint']}>
              达到该轮数后触发自主画像提取，默认 5。
            </span>
          </div>

          {/* 探针触发条件复选框 */}
          <div className={styles['setting-item']}>
            <label>探针触发条件</label>
            {PROBE_OPTIONS.map((option) => (
              <div
                key={option.key}
                className={`${styles['setting-item']} ${styles['checkbox']}`}
                style={{ marginBottom: '12px' }}
              >
                <input
                  type="checkbox"
                  id={`probe-${option.key}`}
                  checked={draftProbeFlags[option.key]}
                  onChange={(e) => onProbeFlagChange(option.key, e.target.checked)}
                />
                <label htmlFor={`probe-${option.key}`} style={{ marginBottom: 0 }}>
                  {option.label}
                  <span className={styles['param-hint-inline']} style={{ marginLeft: '8px' }}>
                    {option.description}
                  </span>
                </label>
              </div>
            ))}
          </div>

          {/* 只读状态信息：距上次提取轮数 + 上次提取时间 */}
          {settings && (
            <div className={styles['setting-item']}>
              <label>当前状态</label>
              <div
                style={{
                  fontSize: '14px',
                  color: 'var(--color-text-secondary)',
                  marginTop: '8px',
                }}
              >
                <p>距上次提取的对话轮数：{settings.turns_since_last_extract}</p>
                <p>上次提取时间：{formatLastExtracted(settings.last_extracted_at)}</p>
              </div>
            </div>
          )}

          <button
            className="btn btn-primary"
            onClick={onSave}
            disabled={!hasChanges || saving}
          >
            {saving ? '保存中...' : '保存设置'}
          </button>
        </>
      )}
    </div>
  )
}

export default ProfileSettingsTab
