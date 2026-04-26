import { defineConfig, devices } from '@playwright/test'

const reuseExistingServer = process.env.OPENAWA_E2E_REUSE_SERVER === 'true'
const frontendPort = Number(process.env.OPENAWA_E2E_FRONTEND_PORT || 15173)
const backendPort = Number(process.env.OPENAWA_E2E_BACKEND_PORT || 18000)

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: /.*electron-smoke\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      testIgnore: /.*electron-smoke\.spec\.ts/,
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'electron',
      testMatch: /.*electron-smoke\.spec\.ts/,
    },
  ],
  webServer: [
    {
      command:
        `python -c "import os, pathlib, uvicorn; db=pathlib.Path('openawa_e2e.db'); db.unlink(missing_ok=True); os.environ['DATABASE_URL']='sqlite:///./openawa_e2e.db'; os.environ['SECRET_KEY']='openawa-e2e-secret'; os.environ['OPENAWA_ADMIN_PASSWORD']='openawa-e2e-admin'; os.environ['OPENAWA_USER_PASSWORD']='openawa-e2e-user'; os.environ['TESTING']='true'; uvicorn.run('main:app', host='127.0.0.1', port=${backendPort})"`,
      cwd: '../backend',
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
