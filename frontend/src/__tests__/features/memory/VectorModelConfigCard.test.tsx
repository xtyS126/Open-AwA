import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import VectorModelConfigCard from '@/features/memory/VectorModelConfigCard'

const { getRegistryMock, getConfigMock, updateConfigMock, downloadModelMock, getDownloadStatusMock } = vi.hoisted(() => ({
  getRegistryMock: vi.fn(),
  getConfigMock: vi.fn(),
  updateConfigMock: vi.fn(),
  downloadModelMock: vi.fn(),
  getDownloadStatusMock: vi.fn(),
}))

vi.mock('@/shared/api/vectorModelsApi', () => ({
  vectorModelsAPI: {
    getRegistry: getRegistryMock,
    getConfig: getConfigMock,
    updateConfig: updateConfigMock,
    downloadModel: downloadModelMock,
    getDownloadStatus: getDownloadStatusMock,
  },
}))

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  })
}

function renderCard() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <VectorModelConfigCard />
    </QueryClientProvider>,
  )
}

describe('VectorModelConfigCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getRegistryMock.mockResolvedValue({
      data: {
        data: {
          models: [
            { name: 'all-MiniLM-L6-v2', kind: 'local', label: '本地', model_type: 'embedding', dimension: 384, downloaded: true, capabilities: [] },
            { name: 'bge-small-zh-v1.5', kind: 'local', label: '中文', model_type: 'embedding', dimension: 512, downloaded: false, capabilities: [] },
            { name: 'Qwen3-VL-Embedding', kind: 'cloud', label: '云端', model_type: 'embedding', dimension: null, downloaded: true, capabilities: ['multimodal'] },
            { name: 'ms-marco-MiniLM-L6-v2', kind: 'local', label: '重排', model_type: 'rerank', dimension: null, downloaded: true, capabilities: [] },
            { name: 'Qwen3-VL-Reranker', kind: 'cloud', label: '云端重排', model_type: 'rerank', dimension: null, downloaded: true, capabilities: ['multimodal'] },
          ],
        },
      },
    })
    getConfigMock.mockResolvedValue({
      data: {
        data: {
          embedding_provider: 'auto',
          embedding_model: 'all-MiniLM-L6-v2',
          embedding_api_key: '',
          embedding_api_endpoint: '',
          rerank_provider: 'off',
          rerank_model: '',
          rerank_api_key: '',
          rerank_api_endpoint: '',
          model_download_source: 'modelscope',
        },
      },
    })
    getDownloadStatusMock.mockResolvedValue({ data: { data: { tasks: {} } } })
    downloadModelMock.mockResolvedValue({ data: { success: true, task: 'embedding:bge-small-zh-v1.5' } })
    updateConfigMock.mockResolvedValue({ data: { success: true, message: 'ok' } })
  })

  it('Spec memory-model-config-chain：注册表模型渲染为可选项', async () => {
    renderCard()

    expect(await screen.findByLabelText('嵌入模型')).toBeInTheDocument()
    expect(screen.getByLabelText('重排模型')).toBeInTheDocument()
    expect(screen.getByLabelText('模型下载源')).toBeInTheDocument()
    // 下载源默认魔搭
    expect((screen.getByLabelText('模型下载源') as HTMLSelectElement).value).toBe('modelscope')
  })

  it('Spec memory-model-config-chain：未下载的本地模型显示下载按钮并触发下载 API', async () => {
    renderCard()

    // 等待配置回填（select 显示已配置模型）
    await waitFor(() => {
      expect((screen.getByLabelText('嵌入模型') as HTMLSelectElement).value).toBe('all-MiniLM-L6-v2')
    })
    const select = screen.getByLabelText('嵌入模型') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'bge-small-zh-v1.5' } })

    await waitFor(() => expect(screen.getByText('下载模型')).toBeInTheDocument())
    fireEvent.click(screen.getByText('下载模型'))

    await waitFor(() => expect(downloadModelMock).toHaveBeenCalledWith('bge-small-zh-v1.5', 'embedding'))
  })

  it('Spec memory-model-config-chain：保存配置调用 updateConfig（本地嵌入 + 重排关闭）', async () => {
    renderCard()

    // 等待配置回填后再保存
    await waitFor(() => {
      expect((screen.getByLabelText('嵌入模型') as HTMLSelectElement).value).toBe('all-MiniLM-L6-v2')
    })
    fireEvent.click(screen.getByText('保存配置'))

    await waitFor(() => expect(updateConfigMock).toHaveBeenCalled())
    const payload = updateConfigMock.mock.calls[0][0]
    expect(payload.embedding_provider).toBe('local')
    expect(payload.embedding_model).toBe('all-MiniLM-L6-v2')
    expect(payload.rerank_provider).toBe('off')
    expect(payload.model_download_source).toBe('modelscope')
  })

  it('Spec memory-model-config-chain：云端嵌入模型时显示 API 配置输入', async () => {
    renderCard()

    await waitFor(() => {
      expect((screen.getByLabelText('嵌入模型') as HTMLSelectElement).value).toBe('all-MiniLM-L6-v2')
    })
    const select = screen.getByLabelText('嵌入模型') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'Qwen3-VL-Embedding' } })

    await waitFor(() => expect(screen.getByPlaceholderText('https://.../v1/embeddings')).toBeInTheDocument())
  })
})
