/**
 * SillyTavernConnectionCard 酒馆AI生图接入说明卡片测试
 * 覆盖：无生图模型时隐藏、有生图模型时展示连接信息、后端根地址推导、复制交互
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { SillyTavernConnectionCard } from '@/features/settings/components/ModelsTab/SillyTavernConnectionCard'

// mock client 模块：避免 axios 实例等副作用，并允许用例内切换 API_BASE_URL
const writeTextMock = vi.fn().mockResolvedValue(undefined)
vi.stubGlobal('navigator', {
  ...navigator,
  clipboard: { writeText: writeTextMock },
})

const clientMock = vi.hoisted(() => ({ API_BASE_URL: '/api' }))
vi.mock('@/shared/api/client', () => clientMock)

afterEach(() => {
  vi.clearAllMocks()
})

describe('SillyTavernConnectionCard 酒馆AI连接说明', () => {
  it('无生图模型时不渲染卡片', () => {
    const { container } = render(<SillyTavernConnectionCard imageModelCount={0} />)
    expect(container.firstChild).toBeNull()
  })

  it('有生图模型时展示连接地址与认证格式', () => {
    render(<SillyTavernConnectionCard imageModelCount={2} />)
    // 标题与模型数量徽标
    expect(screen.getByText(/酒馆AI（SillyTavern）生图接入/)).toBeInTheDocument()
    expect(screen.getByText(/已配置 2 个生图模型/)).toBeInTheDocument()
    // 相对路径模式下连接地址为当前页面 origin
    expect(screen.getByText(window.location.origin)).toBeInTheDocument()
    // 认证格式说明
    expect(screen.getByText(/任意用户名:OpenAwA访问密钥/)).toBeInTheDocument()
  })

  it('桌面端绝对地址模式下剥掉 /api 前缀推导后端根地址', () => {
    clientMock.API_BASE_URL = 'http://192.168.1.100:8000/api'
    render(<SillyTavernConnectionCard imageModelCount={1} />)
    expect(screen.getByText('http://192.168.1.100:8000')).toBeInTheDocument()
    clientMock.API_BASE_URL = '/api'
  })

  it('点击复制按钮调用剪贴板并短暂显示已复制', async () => {
    vi.useFakeTimers()
    try {
      render(<SillyTavernConnectionCard imageModelCount={1} />)
      fireEvent.click(screen.getAllByText('复制')[0])
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(writeTextMock).toHaveBeenCalledWith(window.location.origin)
      expect(screen.getByText('已复制')).toBeInTheDocument()
      // 2 秒后恢复"复制"文案
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(screen.getAllByText('复制').length).toBeGreaterThan(0)
    } finally {
      vi.useRealTimers()
    }
  })
})
