import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { loginAsAdminPage } from './auth'

interface AxeNodeResult {
  html: string
  target: string[]
  failureSummary?: string
}

interface AxeViolationResult {
  id: string
  impact: string | null
  help: string
  nodes: AxeNodeResult[]
}

interface AxeRunResult {
  violations: AxeViolationResult[]
}

const axeSource = readFileSync(
  join(process.cwd(), 'node_modules', 'axe-core', 'axe.min.js'),
  'utf8',
)

async function runAxe(page: Page): Promise<AxeViolationResult[]> {
  await page.addScriptTag({ content: axeSource })
  const result = await page.evaluate(async () => {
    const axe = (window as Window & {
      axe: {
        run: (
          root: Document,
          options: Record<string, unknown>,
        ) => Promise<AxeRunResult>
      }
    }).axe
    return axe.run(document, {
      runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'],
      },
    })
  })

  return result.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  )
}

test.describe('评分提升可访问性发布门禁', () => {
  test('认证状态发布前已完成 CSRF 初始化', async ({ page }) => {
    const ticketResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/security/permissions/sse-ticket'),
      { timeout: 30_000 },
    )

    await loginAsAdminPage(page)

    const ticketResponse = await ticketResponsePromise
    const requestHeaders = await ticketResponse.request().allHeaders()
    expect(ticketResponse.status()).toBe(200)
    expect(requestHeaders.authorization).toMatch(/^Bearer /)
    expect(requestHeaders['x-csrf-token']).toBeTruthy()
    expect(requestHeaders.cookie).toContain('csrf_access_token=')
  })

  test('Chat、Dashboard、Settings 无严重或关键 WCAG 2.2 AA 违规', async ({ page }) => {
    await loginAsAdminPage(page)

    const failures: Array<{ route: string; violations: AxeViolationResult[] }> = []
    for (const route of ['/chat', '/dashboard', '/settings']) {
      await page.goto(route)
      await expect(page.locator('main')).toBeVisible({ timeout: 20_000 })
      await page.waitForTimeout(300)
      const violations = await runAxe(page)
      if (violations.length > 0) {
        failures.push({ route, violations })
      }
    }

    if (failures.length > 0) {
      console.log(`A11Y_FAILURES=${JSON.stringify(failures, null, 2)}`)
    }
    expect(failures).toEqual([])
  })
})
