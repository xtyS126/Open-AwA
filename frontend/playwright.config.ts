import { defineConfig, devices } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const reuseExistingServer = process.env.OPENAWA_E2E_REUSE_SERVER
  ? process.env.OPENAWA_E2E_REUSE_SERVER === 'true'
  : false
const frontendPort = Number(process.env.OPENAWA_E2E_FRONTEND_PORT || 15173)
const backendPort = Number(process.env.OPENAWA_E2E_BACKEND_PORT || 18000)
const outputDir = process.env.OPENAWA_E2E_OUTPUT_DIR || (
  process.env.CI === 'true'
    ? 'test-results'
    : join(tmpdir(), `openawa-playwright-${process.pid}`)
)

export default defineConfig({
  testDir: './tests/e2e',
  outputDir,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    locale: 'zh-CN',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /.*setup\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium',
      dependencies: ['setup'],
      testIgnore: [/.*electron-smoke\.spec\.ts/, /.*setup\.spec\.ts/],
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      dependencies: ['setup'],
      testIgnore: [/.*electron-smoke\.spec\.ts/, /.*setup\.spec\.ts/],
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'electron',
      dependencies: ['setup'],
      testMatch: /.*electron-smoke\.spec\.ts/,
    },
  ],
  webServer: [
    {
      command:
        'python tests/e2e/support/start_backend.py',
      cwd: '.',
      url: `http://127.0.0.1:${backendPort}/health`,
      reuseExistingServer,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --mode e2e`,
      cwd: '.',
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer,
      timeout: 120_000,
    },
  ],
})
