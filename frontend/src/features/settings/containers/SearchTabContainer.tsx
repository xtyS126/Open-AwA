/**
 * 搜索配置 Tab 容器组件
 *
 * 职责：
 *   - 在挂载时拉取当前搜索配置（GET /api/search/config）；
 *   - 将 config 注入 SearchTab 展示组件；
 *   - 包装 onSave / onTest 回调，调用对应 API 并通过 Toast 反馈结果；
 *   - 使用 AbortController 取消未完成的请求，避免组件卸载后更新 state；
 *   - 错误以 SearchConfigError 形式上抛，由展示组件负责 UI 反馈。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { SearchTab } from '@/features/settings/components/SearchTab'
import { useNotification } from '@/shared/hooks/useNotification'
import {
  getSearchConfig,
  SearchConfig,
  SearchConfigError,
  SearchConfigTest,
  SearchConfigUpdate,
  SearchTestResult,
  testSearchConfig,
  updateSearchConfig,
} from '@/shared/api/searchConfigApi'

export function SearchTabContainer() {
  // 配置数据状态
  const [config, setConfig] = useState<SearchConfig | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // 通知 hook —— 自动 3 秒后清除消息
  const { message, showNotification } = useNotification(3000)

  // AbortController 引用：用于取消未完成的 GET 请求，避免组件卸载后更新 state
  const abortControllerRef = useRef<AbortController | null>(null)

  /** 加载当前激活的搜索配置 */
  const loadConfig = useCallback(async () => {
    // 取消上一次未完成的请求
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

    setIsLoading(true)
    setError(null)
    try {
      const data = await getSearchConfig()
      // 若请求已被取消（组件卸载或新请求发起），不再更新 state
      if (controller.signal.aborted) return
      setConfig(data)
    } catch (err) {
      if (controller.signal.aborted) return
      const message = err instanceof Error ? err.message : '加载搜索配置失败'
      setError(message)
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false)
      }
    }
  }, [])

  // 挂载时拉取配置
  useEffect(() => {
    void loadConfig()
    // 卸载时取消未完成的请求
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [loadConfig])

  /**
   * 保存配置回调。
   * 成功：刷新本地 config 并 Toast 提示"保存成功"；
   * 失败：抛出 Error 由 SearchTab 在表单内显示错误，并 Toast 提示"保存失败"。
   */
  const handleSave = useCallback(async (update: SearchConfigUpdate): Promise<void> => {
    try {
      const updated = await updateSearchConfig(update)
      setConfig(updated)
      showNotification({ type: 'success', text: '保存成功' })
    } catch (err) {
      // 提取后端 detail（如 SSRF 拒绝原因），透传给展示组件
      const detail = err instanceof SearchConfigError
        ? err.detail
        : err instanceof Error ? err.message : '保存失败'
      showNotification({ type: 'error', text: `保存失败：${detail}` })
      // 重新抛出，让展示组件在表单内显示具体错误；原始错误已通过闭包保留在调用栈中
      throw new Error(detail)
    }
  }, [showNotification])

  /**
   * 测试连通性回调。
   * 成功：返回 SearchTestResult，由展示组件展示结果；
   * 失败：抛出 Error，展示组件显示错误并返回 null。
   */
  const handleTest = useCallback(async (test: SearchConfigTest): Promise<SearchTestResult> => {
    try {
      const result = await testSearchConfig(test)
      if (result.success) {
        showNotification({
          type: 'success',
          text: `测试成功（延迟 ${result.latency_ms}ms，${result.sample_results.length} 条样本结果）`,
        })
      } else {
        showNotification({
          type: 'error',
          text: `测试失败：${result.error ?? '未知错误'}`,
        })
      }
      return result
    } catch (err) {
      const detail = err instanceof SearchConfigError
        ? err.detail
        : err instanceof Error ? err.message : '测试请求失败'
      showNotification({ type: 'error', text: `测试失败：${detail}` })
      throw new Error(detail)
    }
  }, [showNotification])

  return (
    <div className="settings-section">
      {/* 全局通知消息条 —— 容器层负责 Toast 展示 */}
      {message && (
        <div
          className={`message ${message.type === 'success' ? 'success' : 'error'}`}
          role="status"
          aria-live="polite"
          style={{
            padding: '0.75rem 1rem',
            marginBottom: '1rem',
            borderRadius: '0.375rem',
            fontSize: '0.875rem',
            backgroundColor: message.type === 'success' ? '#d1fae5' : '#fee2e2',
            color: message.type === 'success' ? '#065f46' : '#991b1b',
          }}
        >
          {message.text}
        </div>
      )}

      <SearchTab
        config={config}
        isLoading={isLoading}
        error={error}
        onSave={handleSave}
        onTest={handleTest}
      />
    </div>
  )
}
