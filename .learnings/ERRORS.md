## [ERR-20260503-001] frontend-test-command

**Logged**: 2026-05-03T18:42:30+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
`frontend` 目录没有 `npm run vitest` 脚本，单测应使用 `npm test -- <file>` 或直接调用 `vitest run`

### Error
```text
npm error Missing script: "vitest"
```

### Context
- Command attempted: `npm run vitest -- src/__tests__/features/settings/SettingsPage.test.tsx`
- Environment: `d:\代码\Open-AwA\frontend`
- Relevant file: `frontend/package.json`

### Suggested Fix
- 优先使用 `npm test -- <测试文件>` 运行单测
- 如果需要 watch 模式，使用 `npm run test:watch`

### Metadata
- Reproducible: yes
- Related Files: frontend/package.json

### Resolution
- **Resolved**: 2026-05-03T18:42:30+08:00
- **Notes**: 已改用 `npm test -- src/__tests__/features/settings/SettingsPage.test.tsx`，测试通过

---

## [ERR-20260503-002] playwright-e2e-webserver

**Logged**: 2026-05-03T18:55:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
Playwright E2E 默认后端端口被占用或 `openawa_e2e.db` 被锁定时，`config.webServer` 会在启动阶段直接失败

### Error
```text
Error: http://127.0.0.1:18000/health is already used, make sure that nothing is running on the port/url or set reuseExistingServer:true in config.webServer.

PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问: 'openawa_e2e.db'
```

### Context
- Command attempted: `npx playwright test tests/e2e/settings-provider-modal.spec.ts --project=chromium`
- Environment: `d:\代码\Open-AwA\frontend` on Windows 11
- Relevant files: `frontend/playwright.config.ts`, `frontend/tests/e2e/settings-provider-modal.spec.ts`

### Suggested Fix
- 如果 `18000` 已有同项目后端可用，设置 `OPENAWA_E2E_REUSE_SERVER=true` 复用现有服务
- 如果需要独立环境，除了切换端口，还要确保 `openawa_e2e.db` 未被其他进程占用

### Metadata
- Reproducible: yes
- Related Files: frontend/playwright.config.ts, frontend/tests/e2e/settings-provider-modal.spec.ts

### Resolution
- **Resolved**: 2026-05-03T18:55:00+08:00
- **Notes**: 本次改用 `OPENAWA_E2E_REUSE_SERVER=true` 复用现有 `18000` 后端后，Playwright 用例通过

---
