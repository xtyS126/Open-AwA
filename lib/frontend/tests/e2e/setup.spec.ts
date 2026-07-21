import { expect, test } from '@playwright/test'

const E2E_ADMIN_PASSWORD = 'OpenAwAE2e1'

test.describe('首次部署初始化', () => {
  test('全新实例通过页面完成 owner 初始化', async ({ page }) => {
    await page.goto('/')

    await expect(page).toHaveURL(/\/setup$/)
    await expect(page.getByRole('heading', { name: 'Open-AwA 首次部署' })).toBeVisible()

    const initialStatusResponse = await page.request.get('/api/system/init-status')
    expect(initialStatusResponse.ok()).toBeTruthy()
    const initialStatus = await initialStatusResponse.json()
    expect(initialStatus.data.initialized).toBe(false)
    expect(initialStatus.data.has_users).toBe(false)

    await page.getByLabel('密码', { exact: true }).fill('weak')
    await page.getByLabel('确认密码').fill('weak')
    await page.getByRole('button', { name: '完成部署初始化' }).click()
    await expect(page.getByRole('alert')).toHaveText('密码至少需要 8 个字符')

    await page.getByLabel('密码', { exact: true }).fill(E2E_ADMIN_PASSWORD)
    await page.getByLabel('确认密码').fill('OpenAwAE2e2')
    await page.getByRole('button', { name: '完成部署初始化' }).click()
    await expect(page.getByRole('alert')).toHaveText('两次输入的密码不一致')

    await page.getByLabel('确认密码').fill(E2E_ADMIN_PASSWORD)
    await page.getByRole('button', { name: '完成部署初始化' }).click()

    await expect(page).toHaveURL(/\/login$/, { timeout: 10_000 })

    const initializedStatusResponse = await page.request.get('/api/system/init-status')
    expect(initializedStatusResponse.ok()).toBeTruthy()
    const initializedStatus = await initializedStatusResponse.json()
    expect(initializedStatus.data.initialized).toBe(true)
    expect(initializedStatus.data.has_users).toBe(true)
  })
})
