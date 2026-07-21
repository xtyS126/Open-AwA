/**
 * 提示词配置 Tab 容器组件
 * 管理提示词编辑相关的所有状态和数据获取逻辑
 */
import { useCallback, useEffect, useState, lazy, Suspense } from 'react'
import { promptsAPI } from '@/shared/api/api'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { Skeleton } from '@/shared/components/ui/Skeleton'

const PromptsTab = lazy(() => import('@/features/settings/components/PromptsTab').then(m => ({ default: m.PromptsTab })))

export function PromptsTabContainer() {
  const { showNotification } = useNotification(3000)
  const [promptContent, setPromptContent] = useState('')
  const [saving, setSaving] = useState(false)

  /** 加载当前活跃提示词 */
  const loadPrompts = useCallback(async () => {
    try {
      const response = await promptsAPI.getActive()
      if (response.data && response.data.content) {
        setPromptContent(response.data.content)
      }
    } catch {
      appLogger.error({ event: 'prompts_load_failed', message: 'Failed to load prompts', module: 'settings' })
    }
  }, [])

  /** 保存提示词 */
  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const existingPrompts = await promptsAPI.getAll()
      if (existingPrompts.data && existingPrompts.data.length > 0) {
        await promptsAPI.update(existingPrompts.data[0].id, {
          name: 'System Prompt',
          content: promptContent,
          variables: '{}',
          is_active: true
        })
      } else {
        await promptsAPI.create({
          name: 'System Prompt',
          content: promptContent,
          variables: '{}',
        })
      }
      showNotification({ type: 'success', text: '设置保存成功' })
    } catch {
      showNotification({ type: 'error', text: '保存失败，请重试' })
    } finally {
      setSaving(false)
    }
  }, [promptContent, showNotification])

  /** 提示词内容变更 */
  const handlePromptChange = useCallback((content: string) => {
    setPromptContent(content)
  }, [])

  // 挂载时加载提示词
  useEffect(() => {
    loadPrompts()
  }, [loadPrompts])

  return (
    <Suspense fallback={(
      <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
        <Skeleton.Paragraph lines={6} />
      </div>
    )}>
      <PromptsTab
        promptContent={promptContent}
        saving={saving}
        onPromptChange={handlePromptChange}
        onSave={handleSave}
      />
    </Suspense>
  )
}
