import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

const VIEWPORTS = [
  { width: 375, height: 812, mobile: true },
  { width: 480, height: 900, mobile: true },
  { width: 768, height: 1024, mobile: false },
  { width: 1024, height: 768, mobile: false },
  { width: 1440, height: 900, mobile: false },
] as const

test.describe('助手域真实 L2 验收', () => {
  test.use({ viewport: { width: 480, height: 900 } })

  test('会话管理、上下文持久化和五档导航保持一致', async ({ page }) => {
    test.setTimeout(120_000)
    const pageErrors: string[] = []
    const consoleErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    await loginAsAdminPage(page)

    const mobileLocalNav = page.getByRole('navigation', { name: '助手页面导航' })
    await expect(mobileLocalNav).toBeVisible()
    await expect(mobileLocalNav.getByRole('link')).toHaveCount(3)
    await expect(mobileLocalNav.locator('[aria-current="page"]')).toHaveCount(1)

    await mobileLocalNav.getByRole('link', { name: '会话' }).click()
    await expect(page).toHaveURL(/\/assistant\/sessions$/)
    await expect(page.getByRole('heading', { name: '会话管理' })).toBeVisible()
    await expect(page.getByTestId('chat-input-container')).toHaveCount(0)

    await page.getByRole('button', { name: '新建对话' }).click()
    await expect(page).toHaveURL(/\/assistant\/sessions\/[^/]+$/)
    await expect(page.getByTestId('chat-input-container')).toBeVisible()

    await page.getByRole('navigation', { name: '助手页面导航' })
      .getByRole('link', { name: '上下文' })
      .click()
    await expect(page).toHaveURL(/\/assistant\/context$/)
    await expect(page.getByRole('heading', { name: '助手上下文' })).toBeVisible()
    for (const name of ['角色上下文', '项目上下文', '知识上下文', '声音偏好']) {
      await expect(page.getByRole('group', { name })).toBeVisible()
    }

    const saveButton = page.getByRole('button', { name: '保存上下文' })
    await expect(saveButton).toBeEnabled()
    await saveButton.click()
    await expect(page.getByText('上下文已保存')).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { name: '助手上下文' })).toBeVisible()

    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      const localNav = page.getByRole('navigation', { name: '助手页面导航' })
      if (viewport.mobile) {
        await expect(localNav).toBeVisible()
        await expect(localNav.locator('[aria-current="page"]')).toHaveCount(1)
        const targetHeights = await localNav.getByRole('link').evaluateAll((links) =>
          links.map((link) => link.getBoundingClientRect().height),
        )
        expect(targetHeights.every((height) => height >= 44)).toBe(true)
      } else {
        await expect(localNav).toHaveCount(0)
      }

      const hasHorizontalOverflow = await page.evaluate(() =>
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      )
      expect(hasHorizontalOverflow).toBe(false)
    }

    await page.setViewportSize({ width: 480, height: 900 })
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '200%'
    })
    await expect(page.getByRole('navigation', { name: '助手页面导航' })).toBeVisible()
    await expect(page.getByRole('group', { name: '知识上下文' })).toBeVisible()
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
    )).toBe(true)

    expect(pageErrors).toEqual([])
    expect(consoleErrors).toEqual([])
  })
})
