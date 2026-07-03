/**
 * SearchTab 展示组件单元测试
 *
 * 测试目标：
 *   - 渲染分支：加载态、错误态、Provider 单选组、SearXNG 字段、内网访问开关、徽章
 *   - Provider 切换：searxng / duckduckgo / disabled 之间的字段显隐
 *   - 表单校验：base_url 必填、http(s) scheme 约束
 *   - 测试按钮回调：onTest 调用、成功/失败结果展示、loading 与 disabled 状态
 *   - 保存按钮回调：onSave 调用、成功/失败结果展示、loading 与 disabled 状态
 *   - API Key 显示/隐藏切换
 *
 * 设计要点：
 *   - 不 mock 被测组件内部逻辑，仅 mock Container 注入的回调
 *   - 每个测试在 beforeEach 中重置 mock，避免状态泄漏
 *   - 异步断言使用 waitFor，匹配器使用 RTL 的 toBeInTheDocument 等
 */
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  SearchConfig,
  SearchConfigTest,
  SearchConfigUpdate,
  SearchTestResult,
} from '@/shared/api/searchConfigApi'
import { SearchTab } from '@/features/settings/components/SearchTab'
import type { SearchTabProps } from '@/features/settings/components/SearchTab'

/** 构造默认 props：每个测试可通过 overrides 覆盖任意字段 */
function makeProps(overrides: Partial<SearchTabProps> = {}): SearchTabProps {
  return {
    config: null,
    isLoading: false,
    error: null,
    onSave: vi.fn().mockResolvedValue(undefined) as SearchTabProps['onSave'],
    onTest: vi.fn().mockResolvedValue({
      success: true,
      latency_ms: 50,
      sample_results: [],
    }) as SearchTabProps['onTest'],
    ...overrides,
  }
}

/** 构造测试用 SearchConfig：默认 searxng + 私有 IP */
function makeConfig(overrides: Partial<SearchConfig> = {}): SearchConfig {
  return {
    provider: 'searxng',
    base_url: 'http://192.168.2.10:7653/',
    api_key_set: false,
    enabled: true,
    extra_config: {},
    ...overrides,
  }
}

/** 构造成功的测试结果 */
function makeSuccessResult(
  overrides: Partial<SearchTestResult> = {},
): SearchTestResult {
  return {
    success: true,
    latency_ms: 50,
    sample_results: [
      {
        title: '示例结果',
        url: 'https://example.com/sample',
        snippet: '这是示例摘要',
      },
    ],
    ...overrides,
  }
}

/** 构造失败的测试结果 */
function makeFailureResult(
  overrides: Partial<SearchTestResult> = {},
): SearchTestResult {
  return {
    success: false,
    latency_ms: 5000,
    sample_results: [],
    error: 'timeout',
    ...overrides,
  }
}

describe('SearchTab', () => {
  let defaultProps: SearchTabProps

  beforeEach(() => {
    vi.clearAllMocks()
    defaultProps = makeProps()
  })

  describe('渲染测试', () => {
    it('isLoading=true 时显示加载指示器', () => {
      render(<SearchTab {...makeProps({ isLoading: true })} />)

      expect(screen.getByText('正在加载配置...')).toBeInTheDocument()
      expect(screen.getByRole('status')).toBeInTheDocument()
    })

    it('error 字段被设置时显示错误消息', () => {
      render(<SearchTab {...makeProps({ error: '加载失败' })} />)

      const alert = screen.getByRole('alert')
      expect(alert).toHaveTextContent('加载失败')
    })

    it('默认渲染 searxng / duckduckgo / disabled 三个 Provider 单选项', () => {
      render(<SearchTab {...defaultProps} />)

      const radios = screen.getAllByRole('radio')
      expect(radios).toHaveLength(3)
      expect(
        screen.getByRole('radio', { name: 'SearXNG（自建实例）' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('radio', { name: 'DuckDuckGo（内置默认）' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('radio', { name: '禁用搜索' }),
      ).toBeInTheDocument()
    })

    it('provider=searxng 时显示 Base URL 输入框', () => {
      render(<SearchTab {...defaultProps} />)

      // 默认表单状态 provider 为 searxng
      expect(
        screen.getByPlaceholderText('http://192.168.2.10:7653/'),
      ).toBeInTheDocument()
    })

    it('provider=duckduckgo 时不显示 Base URL 输入框', async () => {
      const config = makeConfig({
        provider: 'duckduckgo',
        base_url: null,
      })
      render(<SearchTab {...makeProps({ config })} />)

      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText('http://192.168.2.10:7653/'),
        ).not.toBeInTheDocument()
      })
    })

    it('provider=searxng 时显示 API Key 密码框', () => {
      render(<SearchTab {...defaultProps} />)

      const apiKeyInput = screen.getByPlaceholderText(
        '可选，部分 SearXNG 实例需要鉴权',
      ) as HTMLInputElement
      expect(apiKeyInput).toBeInTheDocument()
      // 默认隐藏密钥，type 应为 password
      expect(apiKeyInput.type).toBe('password')
    })

    it('base_url 指向私有 IP 时显示允许内网访问开关', () => {
      // 默认 DEFAULT_FORM_STATE.baseUrl 即为 192.168.x.x
      render(<SearchTab {...defaultProps} />)

      expect(
        screen.getByRole('switch', { name: '允许内网访问' }),
      ).toBeInTheDocument()
    })

    it('base_url 指向公网时不显示允许内网访问开关', async () => {
      const config = makeConfig({ base_url: 'https://example.com' })
      render(<SearchTab {...makeProps({ config })} />)

      await waitFor(() => {
        expect(
          screen.queryByRole('switch', { name: '允许内网访问' }),
        ).not.toBeInTheDocument()
      })
    })

    it('始终渲染测试连通性按钮与保存按钮', () => {
      render(<SearchTab {...defaultProps} />)

      expect(
        screen.getByRole('button', { name: '测试连通性' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: '保存配置' }),
      ).toBeInTheDocument()
    })

    it('config.api_key_set=true 时显示 API Key 已设置徽章', async () => {
      const config = makeConfig({ api_key_set: true })
      render(<SearchTab {...makeProps({ config })} />)

      // 等待 useEffect 同步 config 到表单状态后再断言徽章渲染
      await waitFor(() => {
        // 徽章为带 aria-label 的 span，非表单元素，用文本查询更稳定
        const badge = screen.getByText('已设置')
        expect(badge).toBeInTheDocument()
        expect(badge.closest('[aria-label]')?.getAttribute('aria-label')).toBe(
          'API Key 已设置',
        )
      })
    })
  })

  describe('Provider 切换测试', () => {
    it('切换到 duckduckgo 时隐藏 Base URL 与 API Key 输入框', async () => {
      render(<SearchTab {...defaultProps} />)

      // 初始为 searxng，输入框存在
      expect(
        screen.getByPlaceholderText('http://192.168.2.10:7653/'),
      ).toBeInTheDocument()

      fireEvent.click(
        screen.getByRole('radio', { name: 'DuckDuckGo（内置默认）' }),
      )

      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText('http://192.168.2.10:7653/'),
        ).not.toBeInTheDocument()
        expect(
          screen.queryByPlaceholderText('可选，部分 SearXNG 实例需要鉴权'),
        ).not.toBeInTheDocument()
      })
    })

    it('切换到 disabled 时隐藏所有 SearXNG 字段', async () => {
      render(<SearchTab {...defaultProps} />)

      fireEvent.click(screen.getByRole('radio', { name: '禁用搜索' }))

      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText('http://192.168.2.10:7653/'),
        ).not.toBeInTheDocument()
        expect(
          screen.queryByPlaceholderText('可选，部分 SearXNG 实例需要鉴权'),
        ).not.toBeInTheDocument()
        expect(
          screen.queryByRole('switch', { name: '允许内网访问' }),
        ).not.toBeInTheDocument()
      })
    })

    it('从 disabled 切换回 searxng 时输入框重新显示', async () => {
      render(<SearchTab {...defaultProps} />)

      // 先切换到 disabled
      fireEvent.click(screen.getByRole('radio', { name: '禁用搜索' }))
      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText('http://192.168.2.10:7653/'),
        ).not.toBeInTheDocument()
      })

      // 再切换回 searxng
      fireEvent.click(
        screen.getByRole('radio', { name: 'SearXNG（自建实例）' }),
      )

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText('http://192.168.2.10:7653/'),
        ).toBeInTheDocument()
        expect(
          screen.getByPlaceholderText('可选，部分 SearXNG 实例需要鉴权'),
        ).toBeInTheDocument()
      })
    })
  })

  describe('表单校验测试', () => {
    it('searxng 模式下 Base URL 为空时保存按钮禁用', () => {
      render(<SearchTab {...defaultProps} />)

      const baseUrlInput = screen.getByPlaceholderText(
        'http://192.168.2.10:7653/',
      ) as HTMLInputElement
      fireEvent.change(baseUrlInput, { target: { value: '' } })

      expect(screen.getByRole('button', { name: '保存配置' })).toBeDisabled()
    })

    it('Base URL 使用 ftp scheme 时保存按钮禁用', () => {
      render(<SearchTab {...defaultProps} />)

      const baseUrlInput = screen.getByPlaceholderText(
        'http://192.168.2.10:7653/',
      ) as HTMLInputElement
      fireEvent.change(baseUrlInput, {
        target: { value: 'ftp://example.com' },
      })

      expect(screen.getByRole('button', { name: '保存配置' })).toBeDisabled()
    })

    it('Base URL 使用 http:// 时保存按钮启用', () => {
      render(<SearchTab {...defaultProps} />)

      const baseUrlInput = screen.getByPlaceholderText(
        'http://192.168.2.10:7653/',
      ) as HTMLInputElement
      fireEvent.change(baseUrlInput, {
        target: { value: 'http://example.com' },
      })

      expect(screen.getByRole('button', { name: '保存配置' })).toBeEnabled()
    })

    it('Base URL 使用 https:// 时保存按钮启用', () => {
      render(<SearchTab {...defaultProps} />)

      const baseUrlInput = screen.getByPlaceholderText(
        'http://192.168.2.10:7653/',
      ) as HTMLInputElement
      fireEvent.change(baseUrlInput, {
        target: { value: 'https://example.com' },
      })

      expect(screen.getByRole('button', { name: '保存配置' })).toBeEnabled()
    })
  })

  describe('测试按钮回调测试', () => {
    it('点击测试按钮时调用 onTest 并传递当前表单值', async () => {
      const onTest = vi
        .fn()
        .mockResolvedValue(makeSuccessResult()) as SearchTabProps['onTest']
      render(<SearchTab {...makeProps({ onTest })} />)

      fireEvent.click(screen.getByRole('button', { name: '测试连通性' }))

      const expectedPayload: SearchConfigTest = {
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key: undefined,
        extra_config: { allow_private_network: false },
      }
      await waitFor(() => {
        expect(onTest).toHaveBeenCalledWith(expectedPayload)
      })
    })

    it('测试成功时显示成功结果与延迟、样本数', async () => {
      const onTest = vi
        .fn()
        .mockResolvedValue(makeSuccessResult()) as SearchTabProps['onTest']
      render(<SearchTab {...makeProps({ onTest })} />)

      fireEvent.click(screen.getByRole('button', { name: '测试连通性' }))

      await waitFor(() => {
        expect(screen.getByText('测试成功')).toBeInTheDocument()
      })
      expect(screen.getByText(/延迟 50ms/)).toBeInTheDocument()
      expect(screen.getByText(/1 条样本结果/)).toBeInTheDocument()
    })

    it('测试失败时显示失败结果与错误消息', async () => {
      const onTest = vi
        .fn()
        .mockResolvedValue(makeFailureResult()) as SearchTabProps['onTest']
      render(<SearchTab {...makeProps({ onTest })} />)

      fireEvent.click(screen.getByRole('button', { name: '测试连通性' }))

      await waitFor(() => {
        expect(screen.getByText('测试失败')).toBeInTheDocument()
      })
      expect(screen.getByText('timeout')).toBeInTheDocument()
    })

    it('测试中显示加载文案', async () => {
      // 通过延迟 resolve 让测试保持 pending 状态
      let resolveTest!: (value: SearchTestResult) => void
      const onTest = vi.fn().mockImplementation(
        () =>
          new Promise<SearchTestResult>((resolve) => {
            resolveTest = resolve
          }),
      ) as SearchTabProps['onTest']
      render(<SearchTab {...makeProps({ onTest })} />)

      fireEvent.click(screen.getByRole('button', { name: '测试连通性' }))

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: '测试连通性' }),
        ).toHaveTextContent('测试中...')
      })

      // 释放 Promise 避免悬挂
      resolveTest(makeSuccessResult())
      await waitFor(() => {
        expect(screen.getByText('测试成功')).toBeInTheDocument()
      })
    })

    it('测试中禁用测试按钮', async () => {
      let resolveTest!: (value: SearchTestResult) => void
      const onTest = vi.fn().mockImplementation(
        () =>
          new Promise<SearchTestResult>((resolve) => {
            resolveTest = resolve
          }),
      ) as SearchTabProps['onTest']
      render(<SearchTab {...makeProps({ onTest })} />)

      fireEvent.click(screen.getByRole('button', { name: '测试连通性' }))

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: '测试连通性' }),
        ).toBeDisabled()
      })

      resolveTest(makeSuccessResult())
      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: '测试连通性' }),
        ).toBeEnabled()
      })
    })
  })

  describe('保存按钮回调测试', () => {
    it('点击保存按钮时调用 onSave 并传递当前表单值', async () => {
      const onSave = vi
        .fn()
        .mockResolvedValue(undefined) as SearchTabProps['onSave']
      render(<SearchTab {...makeProps({ onSave })} />)

      fireEvent.click(screen.getByRole('button', { name: '保存配置' }))

      const expectedPayload: SearchConfigUpdate = {
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key: undefined,
        enabled: true,
        extra_config: { allow_private_network: false },
      }
      await waitFor(() => {
        expect(onSave).toHaveBeenCalledWith(expectedPayload)
      })
    })

    it('保存成功时不显示错误消息', async () => {
      const onSave = vi
        .fn()
        .mockResolvedValue(undefined) as SearchTabProps['onSave']
      render(<SearchTab {...makeProps({ onSave })} />)

      fireEvent.click(screen.getByRole('button', { name: '保存配置' }))

      await waitFor(() => {
        expect(onSave).toHaveBeenCalled()
      })
      // 保存成功后无 formError 显示
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('保存失败时显示错误消息', async () => {
      const onSave = vi
        .fn()
        .mockRejectedValue(new Error('保存失败：网络错误')) as SearchTabProps['onSave']
      render(<SearchTab {...makeProps({ onSave })} />)

      fireEvent.click(screen.getByRole('button', { name: '保存配置' }))

      await waitFor(() => {
        const alert = screen.getByRole('alert')
        expect(alert).toHaveTextContent('保存失败：网络错误')
      })
    })

    it('保存中禁用保存按钮', async () => {
      let resolveSave!: () => void
      const onSave = vi.fn().mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            resolveSave = resolve
          }),
      ) as SearchTabProps['onSave']
      render(<SearchTab {...makeProps({ onSave })} />)

      fireEvent.click(screen.getByRole('button', { name: '保存配置' }))

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: '保存配置' }),
        ).toBeDisabled()
      })

      resolveSave()
      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: '保存配置' }),
        ).toBeEnabled()
      })
    })
  })

  describe('显示/隐藏 API Key 测试', () => {
    it('点击 Eye 图标切换 API Key 可见性', () => {
      render(<SearchTab {...defaultProps} />)

      const apiKeyInput = screen.getByPlaceholderText(
        '可选，部分 SearXNG 实例需要鉴权',
      ) as HTMLInputElement

      // 默认隐藏
      expect(apiKeyInput.type).toBe('password')
      expect(
        screen.getByRole('button', { name: '显示 API Key' }),
      ).toBeInTheDocument()

      // 点击显示明文
      fireEvent.click(screen.getByRole('button', { name: '显示 API Key' }))
      expect(apiKeyInput.type).toBe('text')
      expect(
        screen.getByRole('button', { name: '隐藏 API Key' }),
      ).toBeInTheDocument()

      // 再点击隐藏
      fireEvent.click(screen.getByRole('button', { name: '隐藏 API Key' }))
      expect(apiKeyInput.type).toBe('password')
      expect(
        screen.getByRole('button', { name: '显示 API Key' }),
      ).toBeInTheDocument()
    })
  })
})
