/**
 * 向量模型配置卡片（Spec memory-model-config-chain）。
 *
 * 功能：
 * - 嵌入模型选择（本地/云端分组，含下载状态与维度）
 * - 重排模型选择（可关闭）
 * - 本地模型下载按钮（ModelScope 默认源）
 * - 云端 API 配置（endpoint / api key，仅云端模式显示）
 * - 下载源选择（modelscope / huggingface）
 * - 配置持久化（PUT /api/models/vector/config）
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { vectorModelsAPI, VectorModelRegistryItem, VectorModelConfigData } from '@/shared/api/vectorModelsApi'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './MemoryPage.module.css'

/* 模型图标（芯片） */
const ChipIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="5" y="5" width="14" height="14" rx="2" />
    <rect x="9" y="9" width="6" height="6" />
    <line x1="9" y1="2" x2="9" y2="5" />
    <line x1="15" y1="2" x2="15" y2="5" />
    <line x1="9" y1="19" x2="9" y2="22" />
    <line x1="15" y1="19" x2="15" y2="22" />
    <line x1="2" y1="9" x2="5" y2="9" />
    <line x1="2" y1="15" x2="5" y2="15" />
    <line x1="19" y1="9" x2="22" y2="9" />
    <line x1="19" y1="15" x2="22" y2="15" />
  </svg>
)

/* 下载图标（向下箭头） */
const DownloadIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
)

function VectorModelConfigCard() {
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  /* 配置本地编辑态 */
  const [embeddingModel, setEmbeddingModel] = useState('')
  const [rerankProvider, setRerankProvider] = useState('off')
  const [rerankModel, setRerankModel] = useState('')
  const [embeddingApiKey, setEmbeddingApiKey] = useState('')
  const [embeddingApiEndpoint, setEmbeddingApiEndpoint] = useState('')
  const [rerankApiKey, setRerankApiKey] = useState('')
  const [rerankApiEndpoint, setRerankApiEndpoint] = useState('')
  const [downloadSource, setDownloadSource] = useState('modelscope')
  /* 下载任务状态（task_key → status） */
  const [downloadTasks, setDownloadTasks] = useState<Record<string, string>>({})

  /* 注册表查询 */
  const registryQuery = useQuery({
    queryKey: ['vector-models', 'registry'],
    queryFn: async () => {
      const response = await vectorModelsAPI.getRegistry()
      return response.data.data.models
    },
    retry: false,
  })

  /* 配置查询 */
  const configQuery = useQuery({
    queryKey: ['vector-models', 'config'],
    queryFn: async () => {
      const response = await vectorModelsAPI.getConfig()
      return response.data.data
    },
    retry: false,
  })

  /* 配置加载后回填编辑态（仅首次加载） */
  useEffect(() => {
    if (!configQuery.data) return
    setEmbeddingModel(configQuery.data.embedding_model || 'all-MiniLM-L6-v2')
    setRerankProvider(configQuery.data.rerank_provider || 'off')
    setRerankModel(configQuery.data.rerank_model || 'ms-marco-MiniLM-L6-v2')
    setEmbeddingApiKey(configQuery.data.embedding_api_key || '')
    setEmbeddingApiEndpoint(configQuery.data.embedding_api_endpoint || '')
    setRerankApiKey(configQuery.data.rerank_api_key || '')
    setRerankApiEndpoint(configQuery.data.rerank_api_endpoint || '')
    setDownloadSource(configQuery.data.model_download_source || 'modelscope')
  }, [configQuery.data])

  /* 注册表分组：嵌入 + 重排，本地/云端 */
  const models = registryQuery.data ?? []
  const embeddingModels = useMemo(() => models.filter((m) => m.model_type === 'embedding'), [models])
  const rerankModels = useMemo(() => models.filter((m) => m.model_type === 'rerank'), [models])
  const localEmbeddingModels = embeddingModels.filter((m) => m.kind === 'local')
  const cloudEmbeddingModels = embeddingModels.filter((m) => m.kind === 'cloud')
  const localRerankModels = rerankModels.filter((m) => m.kind === 'local')
  const cloudRerankModels = rerankModels.filter((m) => m.kind === 'cloud')

  /* 下载模型 */
  const handleDownload = useCallback(async (model: VectorModelRegistryItem) => {
    setActionError(null)
    setActionMessage(null)
    try {
      const response = await vectorModelsAPI.downloadModel(model.name, model.model_type)
      setDownloadTasks((prev) => ({ ...prev, [response.data.task]: 'downloading' }))
      setActionMessage(response.data.message)
      // 轮询下载状态
      const taskKey = response.data.task
      const poll = async () => {
        try {
          const statusRes = await vectorModelsAPI.getDownloadStatus()
          const tasks = statusRes.data.data.tasks ?? {}
          const state = tasks[taskKey]
          if (state) {
            setDownloadTasks((prev) => ({ ...prev, [taskKey]: state.status }))
            if (state.status === 'completed') {
              setActionMessage(`模型 ${model.name} 下载完成`)
              void registryQuery.refetch()
            } else if (state.status === 'failed') {
              setActionError(`模型 ${model.name} 下载失败：${state.error ?? '未知错误'}`)
            } else {
              setTimeout(() => void poll(), 3000)
            }
          } else {
            setTimeout(() => void poll(), 3000)
          }
        } catch {
          // 轮询失败静默，等待下次
          setTimeout(() => void poll(), 3000)
        }
      }
      setTimeout(() => void poll(), 2000)
    } catch (error) {
      const message = getErrorMessage(error, '模型下载失败')
      setActionError(message)
      appLogger.error({
        event: 'vector_model_download_failed',
        module: 'memory',
        action: 'download_model',
        status: 'failure',
        message,
        extra: { model: model.name },
      })
    }
  }, [registryQuery])

  /* 保存配置 */
  const handleSave = useCallback(async () => {
    setActionError(null)
    setActionMessage(null)
    const embeddingSpec = embeddingModels.find((m) => m.name === embeddingModel)
    try {
      const payload: Partial<VectorModelConfigData> = {
        embedding_provider: embeddingSpec?.kind === 'cloud' ? 'cloud' : 'local',
        embedding_model: embeddingModel,
        rerank_provider: rerankProvider,
        rerank_model: rerankProvider === 'off' ? '' : rerankModel,
        model_download_source: downloadSource,
      }
      if (embeddingSpec?.kind === 'cloud') {
        if (embeddingApiKey) payload.embedding_api_key = embeddingApiKey
        if (embeddingApiEndpoint) payload.embedding_api_endpoint = embeddingApiEndpoint
      }
      if (rerankProvider === 'cloud') {
        if (rerankApiKey) payload.rerank_api_key = rerankApiKey
        if (rerankApiEndpoint) payload.rerank_api_endpoint = rerankApiEndpoint
      }
      await vectorModelsAPI.updateConfig(payload)
      setActionMessage('向量模型配置已保存，重启服务后生效')
      void configQuery.refetch()
    } catch (error) {
      const message = getErrorMessage(error, '保存配置失败')
      setActionError(message)
      appLogger.error({
        event: 'vector_model_config_save_failed',
        module: 'memory',
        action: 'save_config',
        status: 'failure',
        message,
      })
    }
  }, [embeddingModel, rerankProvider, rerankModel, embeddingApiKey, embeddingApiEndpoint, rerankApiKey, rerankApiEndpoint, downloadSource, embeddingModels, configQuery])

  const embeddingSpec = embeddingModels.find((m) => m.name === embeddingModel)
  const downloadState = embeddingSpec ? downloadTasks[`embedding:${embeddingSpec.name}`] : undefined

  return (
    <div className={styles.sidebarCard}>
      <div className={styles.sidebarHeader}>
        <div className={styles.sidebarIconBox} style={{ background: 'var(--color-chart-5-bg, var(--color-bg-tertiary))' }}>
          <span style={{ color: 'var(--color-chart-5)' }}><ChipIcon /></span>
        </div>
        <h3 className={styles.sidebarTitle}>向量模型配置</h3>
      </div>

      <div className={styles.kvList}>
        {/* 嵌入模型选择 */}
        <div className={styles.configField}>
          <span className={styles.kvLabel}>嵌入模型</span>
          <select
            className={styles.configSelect}
            value={embeddingModel}
            onChange={(e) => setEmbeddingModel(e.target.value)}
            aria-label="嵌入模型"
          >
            <optgroup label="本地模型">
              {localEmbeddingModels.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}{m.dimension ? `（${m.dimension}维）` : ''}{m.downloaded ? ' ✓' : ''}
                </option>
              ))}
            </optgroup>
            <optgroup label="云端模型（API）">
              {cloudEmbeddingModels.map((m) => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </optgroup>
          </select>
        </div>

        {/* 本地嵌入模型下载 */}
        {embeddingSpec?.kind === 'local' && !embeddingSpec.downloaded && downloadState !== 'completed' && (
          <div className={styles.configField}>
            <span className={styles.kvLabel}>模型下载</span>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => void handleDownload(embeddingSpec)}
              disabled={downloadState === 'downloading'}
            >
              <DownloadIcon />
              {downloadState === 'downloading' ? '下载中...' : '下载模型'}
            </button>
          </div>
        )}

        {/* 云端嵌入配置 */}
        {embeddingSpec?.kind === 'cloud' && (
          <div className={styles.configField}>
            <span className={styles.kvLabel}>API 地址</span>
            <input
              type="text"
              className={styles.configInput}
              placeholder="https://.../v1/embeddings"
              value={embeddingApiEndpoint}
              onChange={(e) => setEmbeddingApiEndpoint(e.target.value)}
            />
            <span className={styles.kvLabel}>API Key</span>
            <input
              type="password"
              className={styles.configInput}
              placeholder="sk-..."
              value={embeddingApiKey}
              onChange={(e) => setEmbeddingApiKey(e.target.value)}
            />
          </div>
        )}

        {/* 重排模型选择 */}
        <div className={styles.configField}>
          <span className={styles.kvLabel}>重排模型</span>
          <select
            className={styles.configSelect}
            value={rerankProvider === 'off' ? '' : rerankModel}
            onChange={(e) => {
              const value = e.target.value
              if (value === '__off__') {
                setRerankProvider('off')
              } else {
                const spec = rerankModels.find((m) => m.name === value)
                setRerankProvider(spec?.kind === 'cloud' ? 'cloud' : 'local')
                setRerankModel(value)
              }
            }}
            aria-label="重排模型"
          >
            <option value="__off__">关闭重排</option>
            <optgroup label="本地模型">
              {localRerankModels.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}{m.downloaded ? ' ✓' : ''}
                </option>
              ))}
            </optgroup>
            <optgroup label="云端模型（API）">
              {cloudRerankModels.map((m) => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </optgroup>
          </select>
        </div>

        {/* 本地重排模型下载 */}
        {(() => {
          const rerankSpec = rerankModels.find((m) => m.name === rerankModel)
          if (!rerankSpec || rerankSpec.kind !== 'local' || rerankProvider === 'off' || rerankSpec.downloaded) return null
          const taskKey = `rerank:${rerankSpec.name}`
          const state = downloadTasks[taskKey]
          return (
            <div className={styles.configField}>
              <span className={styles.kvLabel}>模型下载</span>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => void handleDownload(rerankSpec)}
                disabled={state === 'downloading'}
              >
                <DownloadIcon />
                {state === 'downloading' ? '下载中...' : '下载模型'}
              </button>
            </div>
          )
        })()}

        {/* 云端重排配置 */}
        {rerankProvider === 'cloud' && (
          <div className={styles.configField}>
            <span className={styles.kvLabel}>API 地址</span>
            <input
              type="text"
              className={styles.configInput}
              placeholder="https://.../rerank"
              value={rerankApiEndpoint}
              onChange={(e) => setRerankApiEndpoint(e.target.value)}
            />
            <span className={styles.kvLabel}>API Key</span>
            <input
              type="password"
              className={styles.configInput}
              placeholder="sk-..."
              value={rerankApiKey}
              onChange={(e) => setRerankApiKey(e.target.value)}
            />
          </div>
        )}

        {/* 下载源选择 */}
        <div className={styles.configField}>
          <span className={styles.kvLabel}>下载源</span>
          <select
            className={styles.configSelect}
            value={downloadSource}
            onChange={(e) => setDownloadSource(e.target.value)}
            aria-label="模型下载源"
          >
            <option value="modelscope">魔搭社区（ModelScope）</option>
            <option value="huggingface">HuggingFace</option>
          </select>
        </div>

        {/* 操作区 */}
        <div className={styles.configActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={() => void handleSave()}
          >
            保存配置
          </button>
        </div>

        {actionMessage && <p className={styles.qualityHint}>{actionMessage}</p>}
        {actionError && <p className={styles.configError}>{actionError}</p>}
      </div>
    </div>
  )
}

export default VectorModelConfigCard
