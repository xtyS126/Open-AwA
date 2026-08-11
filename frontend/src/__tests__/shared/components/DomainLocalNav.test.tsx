import '@testing-library/jest-dom/vitest'
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DomainLocalNav from '@/shared/components/DomainLocalNav/DomainLocalNav'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useI18nStore } from '@/i18n'

const originalMatchMedia = window.matchMedia

function installViewport(width: number): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn((query: string) => {
      const minWidth = query.match(/min-width:\s*(\d+(?:\.\d+)?)/)?.[1]
      const maxWidth = query.match(/max-width:\s*(\d+(?:\.\d+)?)/)?.[1]
      const matches = (minWidth === undefined || width >= Number(minWidth))
        && (maxWidth === undefined || width <= Number(maxWidth))

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
    }),
  })
}

describe('DomainLocalNav', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    installViewport(480)
  })

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    })
  })

  it('在助手深链中投影三个 L2 且仅会话项为当前页', () => {
    render(
      <MemoryRouter initialEntries={['/assistant/sessions/session-42']}>
        <DomainLocalNav />
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation', { name: '助手页面导航' })
    const links = within(nav).getAllByRole('link')

    expect(links).toHaveLength(3)
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/assistant',
      '/assistant/sessions',
      '/assistant/context',
    ])
    expect(within(nav).getByRole('link', { name: '会话' }))
      .toHaveAttribute('aria-current', 'page')
    expect(links.filter((link) => link.hasAttribute('aria-current'))).toHaveLength(1)
  })

  it('全局页面不渲染域内导航', () => {
    render(
      <MemoryRouter initialEntries={['/settings/general']}>
        <DomainLocalNav />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('navigation', { name: /页面导航/ })).not.toBeInTheDocument()
  })

  it('768 像素及以上不渲染域内导航', () => {
    installViewport(768)
    const { container } = render(
      <MemoryRouter initialEntries={['/assistant']}>
        <DomainLocalNav />
      </MemoryRouter>,
    )

    expect(container.querySelector('nav')).toBeNull()
  })
})
