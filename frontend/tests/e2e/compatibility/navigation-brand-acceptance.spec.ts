import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { expect, test } from '@playwright/test'

interface AcceptanceResult {
  screenshot: string
  font_scale_screenshot: string | null
  page_errors: string[]
  console_errors: string[]
}

interface AcceptancePayload {
  output_dir: string
  results: AcceptanceResult[]
}

test('五档导航与品牌验收脚本在隔离服务中通过', async () => {
  test.setTimeout(180_000)

  const defaultPython = process.platform === 'win32'
    ? resolve(process.cwd(), '..', '.venv', 'Scripts', 'python.exe')
    : 'python'
  const pythonExecutable = process.env.OPENAWA_E2E_PYTHON || defaultPython
  const result = spawnSync(
    pythonExecutable,
    ['scripts/navigation_brand_acceptance.py'],
    {
      cwd: process.cwd(),
      encoding: 'utf8',
      env: {
        ...process.env,
        OPENAWA_E2E_BACKEND_PORT: process.env.OPENAWA_E2E_BACKEND_PORT || '18000',
        OPENAWA_E2E_FRONTEND_PORT: process.env.OPENAWA_E2E_FRONTEND_PORT || '15173',
      },
      timeout: 150_000,
    },
  )

  expect(
    result.status,
    `验收脚本失败\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}\n${result.error ?? ''}`,
  ).toBe(0)

  const payload = JSON.parse(result.stdout) as AcceptancePayload
  expect(payload.results).toHaveLength(5)
  for (const viewportResult of payload.results) {
    expect(viewportResult.page_errors).toEqual([])
    expect(viewportResult.console_errors).toEqual([])
    expect(existsSync(viewportResult.screenshot)).toBe(true)
    if (viewportResult.font_scale_screenshot) {
      expect(existsSync(viewportResult.font_scale_screenshot)).toBe(true)
    }
  }
})
