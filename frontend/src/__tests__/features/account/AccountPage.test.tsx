import '@testing-library/jest-dom/vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AccountPage from '@/features/account/AccountPage'
import { renderWithRouter } from '@/shared/routing/testing'

vi.mock('@/features/user/UserCenterPage', () => ({
  default: ({
    activeSection,
    hideHeader,
    onSectionChange,
  }: {
    activeSection?: string
    hideHeader?: boolean
    onSectionChange?: (section: 'personal' | 'overview' | 'facts' | 'soul') => void
  }) => (
    <div data-testid={`account-${activeSection}`}>
      账户分区：{hideHeader ? '隐藏标题' : '显示标题'}
      <button type="button" onClick={() => onSectionChange?.('facts')}>切换事实</button>
    </div>
  ),
}))

describe('AccountPage', () => {
  it('旧画像分区映射到统一账户的洋葱画像内容', async () => {
    renderWithRouter(<AccountPage />, {
      initialEntry: '/account?section=profile',
      routePath: '/account',
    })

    expect(await screen.findByTestId('account-soul')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '账户' })).toBeInTheDocument()
  })

  it('账户内切换分区时同步规范 URL', async () => {
    const { router } = renderWithRouter(<AccountPage />, {
      initialEntry: '/account?section=personal',
      routePath: '/account',
    })

    fireEvent.click(await screen.findByRole('button', { name: '切换事实' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/account?section=facts')
    })
  })

  it('离开账户页时不把其他页面的 section 查询参数误判为账户分区', async () => {
    const { router } = renderWithRouter(<AccountPage />, {
      initialEntry: '/account?section=profile',
    })

    await screen.findByTestId('account-soul')
    await act(async () => {
      await router.navigate({ to: '/settings/appearance?section=companion' })
    })

    await waitFor(() => {
      expect(router.state.location.href).toBe('/settings/appearance?section=companion')
    })
  })
})
