import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from './auth'

test('洋葱画像接口只携带一层 API 前缀并成功加载', async ({ page }) => {
  const soulRequestUrls: string[] = []
  const pageErrors: string[] = []

  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/soul/')) {
      soulRequestUrls.push(request.url())
    }
  })
  page.on('pageerror', (error) => {
    pageErrors.push(error.message)
  })

  await loginAsAdminPage(page)
  await page.goto('/user')

  const profileResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/soul/profile',
  )
  const probesResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/soul/probes',
  )

  await page.getByRole('button', { name: '洋葱画像' }).click()

  const [profile, probes] = await Promise.all([profileResponse, probesResponse])
  expect(profile.status()).toBe(200)
  expect(probes.status()).toBe(200)
  await expect(page.getByRole('heading', { name: '五层画像' })).toBeVisible()

  expect(soulRequestUrls.length).toBeGreaterThanOrEqual(2)
  expect(soulRequestUrls.some((url) => new URL(url).pathname === '/api/soul/profile')).toBe(true)
  expect(soulRequestUrls.some((url) => new URL(url).pathname === '/api/soul/probes')).toBe(true)
  expect(soulRequestUrls.every((url) => !url.includes('/api/api/soul/'))).toBe(true)
  expect(pageErrors).toEqual([])
})
