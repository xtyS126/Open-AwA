import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AutomationsOverviewPage from '@/features/automations/AutomationsOverviewPage'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'

describe('AutomationsOverviewPage', () => {
  it('提供自动化生命周期的四个规范入口', () => {
    render(
      <MemoryRouter initialEntries={['/automations/overview']}>
        <AutomationsOverviewPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '自动化概览' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /流程/ })).toHaveAttribute('href', '/automations/flows')
    expect(screen.getByRole('link', { name: /计划/ })).toHaveAttribute('href', '/automations/schedules')
    expect(screen.getByRole('link', { name: /执行者/ })).toHaveAttribute('href', '/automations/executors')
    expect(screen.getByRole('link', { name: /运行/ })).toHaveAttribute('href', '/automations/runs')
  })
})
