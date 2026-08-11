import { expect, test, type Locator, type Page } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

const DOMAIN_TAB_IDS = [
  'tab-assistant',
  'tab-workbench',
  'tab-automations',
  'tab-library',
  'tab-activity',
] as const

async function loginAndWaitForShell(page: Page): Promise<void> {
  await loginAsAdminPage(page)
  await page.waitForLoadState('domcontentloaded')
  await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
}

async function expectFiveDomainLinks(navigation: Locator): Promise<void> {
  await expect(navigation.getByRole('link')).toHaveCount(5)
}

/**
 * A3 响应式导航契约：
 * - 小于 768px：五域底栏，二级入口由页面内导航承载；
 * - 768 至 1023px：领域轨道配合临时子导航；
 * - 1024 至 1439px：领域轨道配合可折叠子导航；
 * - 1440px 及以上：领域轨道配合永久子导航。
 */
test.describe('A3 响应式导航布局', () => {
  test.describe('移动端五域底栏 (480×800)', () => {
    test.use({ viewport: { width: 480, height: 800 } })

    test('只显示五域底栏并隐藏桌面导航', async ({ page }) => {
      await loginAndWaitForShell(page)

      const bottomNavigation = page.getByRole('navigation', { name: '底部主导航' })
      await expect(bottomNavigation).toBeVisible()
      await expectFiveDomainLinks(bottomNavigation)

      for (const testId of DOMAIN_TAB_IDS) {
        await expect(bottomNavigation.getByTestId(testId)).toBeVisible()
      }
      await expect(bottomNavigation.getByTestId('tab-assistant'))
        .toHaveAttribute('aria-current', 'page')

      await expect(page.getByTestId('sidebar')).toBeHidden()
      await expect(page.getByRole('navigation', { name: '工作域' })).toBeHidden()
    })
  })

  test.describe('平板临时子导航 (768×1024)', () => {
    test.use({ viewport: { width: 768, height: 1024 } })

    test('领域轨道常驻且子导航按需临时展开', async ({ page }) => {
      await loginAndWaitForShell(page)

      const sidebar = page.getByTestId('sidebar')
      const domainNavigation = page.getByRole('navigation', { name: '工作域' })
      await expect(sidebar).toBeVisible()
      await expect(sidebar).toHaveAttribute('data-layout', 'temporary')
      await expect(sidebar).toHaveAttribute('data-collapsed', 'true')
      await expectFiveDomainLinks(domainNavigation)
      await expect(page.getByRole('navigation', { name: '底部主导航' })).toHaveCount(0)
      await expect(page.getByTestId('chat-input-container')).toBeVisible()
      await expect(page.getByTestId('chat-input-container')).not.toHaveCSS('position', 'fixed')

      await page.getByRole('button', { name: '展开子导航' }).click()
      await expect(sidebar).toHaveAttribute('data-collapsed', 'false')

      const subnavigation = page.getByRole('navigation', { name: '助手子导航' })
      await expect(subnavigation).toBeVisible()
      await subnavigation.getByRole('link').first().click()
      await expect(sidebar).toHaveAttribute('data-collapsed', 'true')
    })
  })

  test.describe('中型桌面可折叠子导航 (1024×768)', () => {
    test.use({ viewport: { width: 1024, height: 768 } })

    test('子导航可收起和恢复且五域轨道保持可用', async ({ page }) => {
      await loginAndWaitForShell(page)

      const sidebar = page.getByTestId('sidebar')
      const domainNavigation = page.getByRole('navigation', { name: '工作域' })
      await expect(sidebar).toBeVisible()
      await expect(sidebar).toHaveAttribute('data-layout', 'collapsible')
      await expect(sidebar).toHaveAttribute('data-collapsed', 'false')
      await expectFiveDomainLinks(domainNavigation)
      await expect(page.getByRole('navigation', { name: '助手子导航' })).toBeVisible()

      await page.getByRole('button', { name: '收起子导航' }).click()
      await expect(sidebar).toHaveAttribute('data-collapsed', 'true')
      await expect(page.getByRole('navigation', { name: '助手子导航' })).toHaveCount(0)
      await expectFiveDomainLinks(domainNavigation)

      await page.getByRole('button', { name: '展开子导航' }).click()
      await expect(sidebar).toHaveAttribute('data-collapsed', 'false')
      await expect(page.getByRole('navigation', { name: '助手子导航' })).toBeVisible()
    })
  })

  test.describe('宽屏永久子导航 (1440×900)', () => {
    test.use({ viewport: { width: 1440, height: 900 } })

    test('忽略中型桌面的折叠偏好并默认永久展开', async ({ page }) => {
      await page.addInitScript(() => {
        window.localStorage.setItem('openawa.sidebar.subnav-collapsed', 'true')
      })
      await loginAndWaitForShell(page)

      const sidebar = page.getByTestId('sidebar')
      const domainNavigation = page.getByRole('navigation', { name: '工作域' })
      await expect(sidebar).toBeVisible()
      await expect(sidebar).toHaveAttribute('data-layout', 'wide')
      await expect(sidebar).toHaveAttribute('data-collapsed', 'false')
      await expectFiveDomainLinks(domainNavigation)
      await expect(page.getByRole('navigation', { name: '助手子导航' })).toBeVisible()
      await expect(page.getByRole('navigation', { name: '底部主导航' })).toHaveCount(0)
    })
  })
})
