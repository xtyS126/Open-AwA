import '@testing-library/jest-dom/vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PersonaLibraryPage from '@/features/library/PersonaLibraryPage'
import { renderWithRouter } from '@/shared/routing/testing'

vi.mock('@/features/roles/RolesPage', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="personas-installed">已有角色：{embedded ? '嵌入' : '独立'}</div>
  ),
}))

vi.mock('@/features/marketplace/RoleMarketPage', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="personas-discover">发现角色：{embedded ? '嵌入' : '独立'}</div>
  ),
}))

describe('PersonaLibraryPage', () => {
  it.each([
    ['/library/personas?view=installed', 'personas-installed'],
    ['/library/personas?view=discover', 'personas-discover'],
  ])('按查询状态渲染 %s', async (initialEntry, testId) => {
    renderWithRouter(<PersonaLibraryPage />, {
      initialEntry,
      routePath: '/library/personas',
    })

    expect(await screen.findByTestId(testId)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '角色资源' })).toBeInTheDocument()
  })

  it('切换发现视图时同步规范 URL', async () => {
    const { router } = renderWithRouter(<PersonaLibraryPage />, {
      initialEntry: '/library/personas?view=installed',
      routePath: '/library/personas',
    })

    await screen.findByTestId('personas-installed')
    fireEvent.click(screen.getByRole('tab', { name: '发现角色' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/library/personas?view=discover')
    })
    expect(await screen.findByTestId('personas-discover')).toBeInTheDocument()
  })

  it('离开角色资源页时不再用默认视图覆盖目标路由', async () => {
    const { router } = renderWithRouter(<PersonaLibraryPage />, {
      initialEntry: '/library/personas?view=discover',
    })

    await screen.findByTestId('personas-discover')
    await act(async () => {
      await router.navigate({ to: '/settings/general' })
    })

    await waitFor(() => {
      expect(router.state.location.href).toBe('/settings/general')
    })
  })
})
