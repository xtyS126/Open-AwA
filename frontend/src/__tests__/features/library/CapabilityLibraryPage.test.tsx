import '@testing-library/jest-dom/vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CapabilityLibraryPage from '@/features/library/CapabilityLibraryPage'
import { renderWithRouter } from '@/shared/routing/testing'

vi.mock('@/features/skills/SkillsPage', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="skills-installed">技能已安装视图：{embedded ? '嵌入' : '独立'}</div>
  ),
}))

vi.mock('@/features/skills/SkillMarketPage', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="skills-discover">技能发现视图：{embedded ? '嵌入' : '独立'}</div>
  ),
}))

vi.mock('@/features/plugins/PluginsPage', () => ({
  default: ({
    activeTab,
    hideTabs,
  }: {
    activeTab?: 'installed' | 'market'
    hideTabs?: boolean
  }) => (
    <div data-testid={`plugins-${activeTab}`}>
      插件视图：{activeTab}；{hideTabs ? '隐藏内部标签' : '显示内部标签'}
    </div>
  ),
}))

describe('CapabilityLibraryPage', () => {
  it.each([
    ['/library/capabilities?type=skill&view=installed', 'skills-installed'],
    ['/library/capabilities?type=skill&view=discover', 'skills-discover'],
    ['/library/capabilities?type=plugin&view=installed', 'plugins-installed'],
    ['/library/capabilities?type=plugin&view=discover', 'plugins-market'],
  ])('按规范查询状态渲染 %s', async (initialEntry, testId) => {
    renderWithRouter(<CapabilityLibraryPage />, {
      initialEntry,
      routePath: '/library/capabilities',
    })

    expect(await screen.findByTestId(testId)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '能力资源' })).toBeInTheDocument()
  })

  it('切换能力类型和视图时同步规范 URL', async () => {
    const { router } = renderWithRouter(<CapabilityLibraryPage />, {
      initialEntry: '/library/capabilities?type=skill&view=installed',
      routePath: '/library/capabilities',
    })

    await screen.findByTestId('skills-installed')
    fireEvent.click(screen.getByRole('tab', { name: '插件' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/library/capabilities?type=plugin&view=installed')
    })
    expect(await screen.findByTestId('plugins-installed')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '发现' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/library/capabilities?type=plugin&view=discover')
    })
    expect(await screen.findByTestId('plugins-market')).toBeInTheDocument()
  })

  it('无效查询状态回落为技能已安装视图并替换 URL', async () => {
    const { router } = renderWithRouter(<CapabilityLibraryPage />, {
      initialEntry: '/library/capabilities?type=unknown&view=broken',
      routePath: '/library/capabilities',
    })

    expect(await screen.findByTestId('skills-installed')).toBeInTheDocument()
    await waitFor(() => {
      expect(router.state.location.href).toBe('/library/capabilities?type=skill&view=installed')
    })
  })

  it('离开能力资源页时不再用默认查询状态覆盖目标路由', async () => {
    const { router } = renderWithRouter(<CapabilityLibraryPage />, {
      initialEntry: '/library/capabilities?type=plugin&view=installed',
    })

    await screen.findByTestId('plugins-installed')
    await act(async () => {
      await router.navigate({ to: '/settings/general' })
    })

    await waitFor(() => {
      expect(router.state.location.href).toBe('/settings/general')
    })
  })
})
