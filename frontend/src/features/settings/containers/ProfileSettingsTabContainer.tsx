/**
 * 用户画像设置 Tab 容器组件
 * 管理画像设置的状态与 API 调用，将数据与回调通过 props 传递给展示组件。
 *
 * 设计要点：
 *   - 加载时调用 GET /api/profile/settings 获取已保存设置
 *   - 草稿（draftNThreshold / draftProbeFlags）与已保存值分离，
 *     仅当草稿与已保存值存在差异时启用"保存设置"按钮
 *   - 保存时调用 PUT /api/profile/settings，仅传变更字段
 *   - 保存成功/失败通过 useNotification 显示 toast
 */
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import {
  getProfileSettings,
  updateProfileSettings,
  type ProfileSettings,
  type ProbeFlags,
} from '@/shared/api/profileApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// 懒加载展示组件，减少首屏 bundle 体积
const ProfileSettingsTab = lazy(() =>
  import('@/features/settings/components/ProfileSettings').then((m) => ({
    default: m.ProfileSettingsTab,
  })),
)

/** 探针 flags 默认值（后端返回空 dict 时使用） */
const DEFAULT_PROBE_FLAGS: ProbeFlags = {
  low_confidence: false,
  new_interest: false,
  periodic_review: false,
}

/** N 值默认值（后端返回的默认值） */
const DEFAULT_N_THRESHOLD = 5

/** 将后端返回的 probe_flags 归一化为完整结构，确保三个 key 都存在 */
const normalizeProbeFlags = (flags: Partial<ProbeFlags> | undefined): ProbeFlags => ({
  low_confidence: flags?.low_confidence ?? false,
  new_interest: flags?.new_interest ?? false,
  periodic_review: flags?.periodic_review ?? false,
})

/** 懒加载占位符：使用 Skeleton 模拟表单结构 */
function TabLoadingFallback() {
  return (
    <div
      style={{
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
      }}
    >
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

export function ProfileSettingsTabContainer() {
  // 已保存的设置（用于展示只读状态信息 + 变更对比）
  const [settings, setSettings] = useState<ProfileSettings | null>(null)
  // 当前编辑中的 N 值草稿
  const [draftNThreshold, setDraftNThreshold] = useState<number>(DEFAULT_N_THRESHOLD)
  // 当前编辑中的探针 flags 草稿
  const [draftProbeFlags, setDraftProbeFlags] = useState<ProbeFlags>(DEFAULT_PROBE_FLAGS)
  // 加载状态
  const [loading, setLoading] = useState(false)
  // 保存状态
  const [saving, setSaving] = useState(false)

  const { message, showNotification } = useNotification(3000)

  /** 加载画像设置 */
  const loadSettings = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getProfileSettings()
      const normalizedFlags = normalizeProbeFlags(
        data.probe_flags as Partial<ProbeFlags> | undefined,
      )
      const normalized: ProfileSettings = {
        ...data,
        probe_flags: normalizedFlags,
      }
      setSettings(normalized)
      setDraftNThreshold(normalized.n_threshold)
      setDraftProbeFlags(normalized.probe_flags)
    } catch (error) {
      appLogger.error({
        event: 'profile_settings_load_failed',
        module: 'settings',
        message: '加载画像设置失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      setLoading(false)
    }
  }, [])

  /** N 值变更：仅更新本地草稿，不调用 API */
  const handleNThresholdChange = useCallback((value: number) => {
    setDraftNThreshold(value)
  }, [])

  /** 探针 flag 变更：仅更新本地草稿，不调用 API */
  const handleProbeFlagChange = useCallback((key: keyof ProbeFlags, value: boolean) => {
    setDraftProbeFlags((prev) => ({ ...prev, [key]: value }))
  }, [])

  /** 计算草稿与已保存值是否存在差异 */
  const hasChanges = (() => {
    if (!settings) {
      // 未加载到已保存值时，只要草稿非默认值就视为有变更
      return (
        draftNThreshold !== DEFAULT_N_THRESHOLD ||
        draftProbeFlags.low_confidence !== DEFAULT_PROBE_FLAGS.low_confidence ||
        draftProbeFlags.new_interest !== DEFAULT_PROBE_FLAGS.new_interest ||
        draftProbeFlags.periodic_review !== DEFAULT_PROBE_FLAGS.periodic_review
      )
    }
    if (draftNThreshold !== settings.n_threshold) return true
    return (
      draftProbeFlags.low_confidence !== settings.probe_flags.low_confidence ||
      draftProbeFlags.new_interest !== settings.probe_flags.new_interest ||
      draftProbeFlags.periodic_review !== settings.probe_flags.periodic_review
    )
  })()

  /** 保存设置：仅传变更字段 */
  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      // 构造仅含变更字段的载荷
      const payload: { n_threshold?: number; probe_flags?: Partial<ProbeFlags> } = {}
      if (!settings || draftNThreshold !== settings.n_threshold) {
        payload.n_threshold = draftNThreshold
      }
      if (
        !settings ||
        draftProbeFlags.low_confidence !== settings.probe_flags.low_confidence ||
        draftProbeFlags.new_interest !== settings.probe_flags.new_interest ||
        draftProbeFlags.periodic_review !== settings.probe_flags.periodic_review
      ) {
        payload.probe_flags = { ...draftProbeFlags }
      }

      const updated = await updateProfileSettings(payload)
      const normalizedFlags = normalizeProbeFlags(
        updated.probe_flags as Partial<ProbeFlags> | undefined,
      )
      const normalized: ProfileSettings = {
        ...updated,
        probe_flags: normalizedFlags,
      }
      setSettings(normalized)
      setDraftNThreshold(normalized.n_threshold)
      setDraftProbeFlags(normalized.probe_flags)
      showNotification({ type: 'success', text: '画像设置保存成功' })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '画像设置保存失败') })
    } finally {
      setSaving(false)
    }
  }, [settings, draftNThreshold, draftProbeFlags, showNotification])

  // 挂载时加载设置
  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  return (
    <>
      {message && <div className={`message ${message.type}`}>{message.text}</div>}
      <Suspense fallback={<TabLoadingFallback />}>
        <ProfileSettingsTab
          loading={loading}
          settings={settings}
          draftNThreshold={draftNThreshold}
          draftProbeFlags={draftProbeFlags}
          saving={saving}
          hasChanges={hasChanges}
          onLoad={loadSettings}
          onSave={handleSave}
          onNThresholdChange={handleNThresholdChange}
          onProbeFlagChange={handleProbeFlagChange}
        />
      </Suspense>
    </>
  )
}
