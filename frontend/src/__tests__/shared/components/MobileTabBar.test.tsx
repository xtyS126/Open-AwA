import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MobileTabBar } from '@/shared/components/MobileTabBar/MobileTabBar'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useI18nStore } from '@/i18n'

function installViewport(width: number): void {
  const matchMedia = vi.fn((query: string) => {
    const minWidthMatch = query.match(/min-width:\s*(\d+(?:\.\d+)?)/)
    const maxWidthMatch = query.match(/max-width:\s*(\d+(?:\.\d+)?)/)
    const minWidth = minWidthMatch ? Number.parseFloat(minWidthMatch[1]) : null
    const maxWidth = maxWidthMatch ? Number.parseFloat(maxWidthMatch[1]) : null
    let matches = true
    if (minWidth !== null) matches = matches && width >= minWidth
    if (maxWidth !== null) matches = matches && width <= maxWidth
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }
  })

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: matchMedia,
  })
}

describe('MobileTabBar', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    installViewport(390)
  })

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: undefined,
    })
  })

  it('移动端只渲染五个工作域且不再提供更多抽屉', () => {
    render(
      <MemoryRouter initialEntries={['/library/knowledge']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    expect(screen.getAllByRole('link')).toHaveLength(5)
    expect(screen.getByRole('link', { name: /资源库/ }))
      .toHaveAttribute('aria-current', 'page')
    expect(screen.queryByTestId('tab-more')).not.toBeInTheDocument()
  })

  it('规范深链选中所属工作域', () => {
    render(
      <MemoryRouter initialEntries={['/automations/runs/run-1']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /自动化/ }))
      .toHaveAttribute('aria-current', 'page')
  })

  it('迁移期旧路径选中所属工作域', () => {
    render(
      <MemoryRouter initialEntries={['/vibe-coding']}>
        <MobileTabBar />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /工作台/ }))
      .toHaveAttribute('aria-current', 'page')
  })

  it('桌面视口不渲染移动底栏', () => {
    installViewport(1440)

    const { container } = render(
      <MemoryRouter initialEntries={['/assistant']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    expect(container.querySelector('nav')).toBeNull()
  })
})
