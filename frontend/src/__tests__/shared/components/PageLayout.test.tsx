import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PageLayout from '@/shared/components/PageLayout/PageLayout'

describe('PageLayout', () => {
  it('嵌入应用外壳时不创建第二个 main 地标', () => {
    render(
      <main id="main-content">
        <PageLayout title="设置">
          <p>页面内容</p>
        </PageLayout>
      </main>,
    )

    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 1, name: '设置' })).toBeInTheDocument()
  })
})
