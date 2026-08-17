/**
 * 提示词配置 Tab 容器组件
 * 管理提示词编辑相关的所有状态和数据获取逻辑
 *
 * 改造说明（fix-performance-remaining-issues 模块 C）：
 *   - 原实现使用 useEffect + axios，每次 mount 都触发 /api/prompts/active 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多 Tab 切换时复用缓存
 *   - queryKey: ['prompts', 'active']，与 GeneralTabContainer 共享缓存
 *   - 保存成功后失效缓存以触发刷新
 */
import { useCallback, useEffect, useState, lazy, Suspense } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { promptsAPI } from '@/shared/api/api'
import { useNotification } from '@/shared/hooks/useNotification'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { PROMPTS_ACTIVE_QUERY_KEY } from './GeneralTabContainer'

const PromptsTab = lazy(() => import('@/features/settings/components/PromptsTab').then(m => ({ default: m.PromptsTab })))

export function PromptsTabContainer() {
  const { showNotification } = useNotification(3000)
  const queryClient = useQueryClient()
  const [promptContent, setPromptContent] = useState('')
  const [saving, setSaving] = useState(false)

  // 加载当前活跃提示词（与 GeneralTabContainer 共享 ['prompts', 'active'] 缓存）
  const { data: activePrompt } = useQuery({
    queryKey: PROMPTS_ACTIVE_QUERY_KEY,
    queryFn: () => promptsAPI.getActive().then(r => r.data),
  })

  // 提示词加载完成后同步到本地 state（首次加载与保存后刷新均会触发）
  useEffect(() => {
    if (activePrompt?.content) {
      setPromptContent(activePrompt.content)
    }
  }, [activePrompt])

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
      // 失效缓存，触发 useQuery 重新拉取最新活跃提示词
      await queryClient.invalidateQueries({ queryKey: PROMPTS_ACTIVE_QUERY_KEY })
      showNotification({ type: 'success', text: '设置保存成功' })
    } catch {
      showNotification({ type: 'error', text: '保存失败，请重试' })
    } finally {
      setSaving(false)
    }
  }, [promptContent, showNotification, queryClient])

  /** 提示词内容变更 */
  const handlePromptChange = useCallback((content: string) => {
    setPromptContent(content)
  }, [])

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
