import '@testing-library/jest-dom/vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import KnowledgeLibraryPage from '@/features/library/KnowledgeLibraryPage'
import { renderWithRouter } from '@/shared/routing/testing'

vi.mock('@/features/memory/MemoryPage', () => ({
  default: ({ activeTab, hideTabs }: { activeTab?: string; hideTabs?: boolean }) => (
    <div data-testid={`memory-${activeTab}`}>记忆视图：{hideTabs ? '隐藏内部标签' : '显示内部标签'}</div>
  ),
}))

vi.mock('@/features/experiences/ExperiencePage', () => ({
  default: ({ hideHeader }: { hideHeader?: boolean }) => (
    <div data-testid="memory-experience">经验视图：{hideHeader ? '隐藏标题' : '显示标题'}</div>
  ),
}))

describe('KnowledgeLibraryPage', () => {
  it.each([
    ['/library/knowledge?view=short-term', 'memory-short-term'],
    ['/library/knowledge?view=long-term', 'memory-long-term'],
    ['/library/knowledge?view=experience', 'memory-experience'],
    ['/library/knowledge?view=quality', 'memory-quality'],
  ])('按查询状态渲染 %s', async (initialEntry, testId) => {
    renderWithRouter(<KnowledgeLibraryPage />, {
      initialEntry,
      routePath: '/library/knowledge',
    })

    expect(await screen.findByTestId(testId)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '知识资源' })).toBeInTheDocument()
  })

  it('切换经验视图时同步规范 URL', async () => {
    const { router } = renderWithRouter(<KnowledgeLibraryPage />, {
      initialEntry: '/library/knowledge?view=long-term',
      routePath: '/library/knowledge',
    })

    await screen.findByTestId('memory-long-term')
    fireEvent.click(screen.getByRole('tab', { name: '经验' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/library/knowledge?view=experience')
    })
    expect(await screen.findByTestId('memory-experience')).toBeInTheDocument()
  })

  it('离开知识资源页时不再用默认视图覆盖目标路由', async () => {
    const { router } = renderWithRouter(<KnowledgeLibraryPage />, {
      initialEntry: '/library/knowledge?view=experience',
    })

    await screen.findByTestId('memory-experience')
    await act(async () => {
      await router.navigate({ to: '/settings/general' })
    })

    await waitFor(() => {
      expect(router.state.location.href).toBe('/settings/general')
    })
  })
})
