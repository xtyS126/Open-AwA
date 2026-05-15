import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('记忆与经验 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
  })

  test('记忆页面渲染正常', async ({ page }) => {
    await page.goto('/memory')

    // 验证记忆页面基本元素
    const memoryHeading = page.locator('text=记忆').first()
    await expect(memoryHeading).toBeVisible({ timeout: 20_000 })

    // 验证页面正常渲染
    await expect(page.locator('body')).toBeVisible()
  })

  test('记忆列表渲染', async ({ page }) => {
    await page.goto('/memory')

    await expect(page.locator('text=记忆').first()).toBeVisible({ timeout: 20_000 })

    // 查找记忆列表或空状态提示
    const memoryList = page.locator('[role="list"], .memory-list, [data-testid="memory-list"]').first()
    const emptyStateText = page.locator('text=暂无记忆, text=还没有记忆, text=No memories').first()

    const hasList = await memoryList.isVisible({ timeout: 10_000 }).catch(() => false)
    const hasEmptyState = await emptyStateText.isVisible({ timeout: 5_000 }).catch(() => false)

    // 至少应有列表或空状态提示之一
    expect(hasList || hasEmptyState).toBeTruthy()
  })

  test('经验页面渲染正常', async ({ page }) => {
    await page.goto('/experience')

    // 验证经验页面基本元素
    const experienceHeading = page.locator('text=经验').first()
    await expect(experienceHeading).toBeVisible({ timeout: 20_000 })

    // 验证页面正常渲染
    await expect(page.locator('body')).toBeVisible()
  })

  test('经验列表渲染', async ({ page }) => {
    await page.goto('/experience')

    await expect(page.locator('text=经验').first()).toBeVisible({ timeout: 20_000 })

    // 查找经验列表或空状态提示
    const experienceList = page.locator('[role="list"], .experience-list, [data-testid="experience-list"]').first()
    const emptyStateText = page.locator('text=暂无经验, text=还没有经验, text=No experiences').first()

    const hasList = await experienceList.isVisible({ timeout: 10_000 }).catch(() => false)
    const hasEmptyState = await emptyStateText.isVisible({ timeout: 5_000 }).catch(() => false)

    // 至少应有列表或空状态提示之一
    expect(hasList || hasEmptyState).toBeTruthy()
  })

  test('从侧边栏导航到记忆页面', async ({ page }) => {
    await page.goto('/chat')

    // 通过侧边栏导航到记忆页面
    const memoryLink = page.getByRole('link', { name: '记忆' })
    await expect(memoryLink).toBeVisible({ timeout: 15_000 })
    await memoryLink.click()

    await page.waitForURL(/\/memory/, { timeout: 15_000 })
    await expect(page.locator('text=记忆').first()).toBeVisible({ timeout: 10_000 })
  })

  test('从侧边栏导航到经验页面', async ({ page }) => {
    await page.goto('/chat')

    // 通过侧边栏导航到经验页面
    const experienceLink = page.getByRole('link', { name: '经验' })
    await expect(experienceLink).toBeVisible({ timeout: 15_000 })
    await experienceLink.click()

    await page.waitForURL(/\/experience/, { timeout: 15_000 })
    await expect(page.locator('text=经验').first()).toBeVisible({ timeout: 10_000 })
  })
})
