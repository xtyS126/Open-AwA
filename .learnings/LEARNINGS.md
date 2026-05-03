## [LRN-20260501-001] frontend

**Logged**: 2026-05-01T12:00:00Z
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
React Testing Library `renderHook` state updates must be wrapped in `act(...)` to avoid warnings.

### Details
When writing unit tests for custom React hooks using `@testing-library/react` and `vitest`, if the hook performs asynchronous state updates (e.g. fetching data in `useEffect`), the test will output warnings like "Warning: An update to TestComponent inside a test was not wrapped in act(...)". 
To fix this, we must wrap asynchronous operations in `act(async () => { ... })` or use `waitFor` to wait for the loading state to finish before asserting.

### Suggested Action
Always await the initial loading state of a hook using `await waitFor(() => expect(result.current.loading).toBe(false))` right after `renderHook()`. Any interaction that triggers a state update should be wrapped in `await act(async () => { ... })`.

### Metadata
- Source: error
- Related Files: frontend/src/features/chat/wechat-module/__tests__/useWechatConfig.test.ts
- Tags: vitest, react-testing-library, hooks, act

---

## [LRN-20260503-002] best_practice

**Logged**: 2026-05-03T18:56:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: frontend

### Summary
预置供应商的显示名称不能凭经验硬编码，必须以 `PROVIDER_NAMES` 映射为准

### Details
在为 `SettingsPage` 的“新增供应商”弹窗补充 Playwright 用例时，最初假设 `moonshot` 的预置显示名称是 `Moonshot AI`，但项目实际通过 `frontend/src/assets/providers/index.ts` 中的 `PROVIDER_NAMES` 统一定义，`moonshot` 对应的名称是 `Kimi`。如果测试或 UI 自动填充值绕过这份映射，断言会与真实行为不一致。

### Suggested Action
新增供应商相关逻辑、测试和文档都应直接复用 `PROVIDER_NAMES`，不要手写预置供应商显示名称；新增供应商预填显示名时，优先从映射读取。

### Metadata
- Source: error
- Related Files: frontend/src/assets/providers/index.ts, frontend/src/features/settings/SettingsPage.tsx, frontend/tests/e2e/settings-provider-modal.spec.ts
- Tags: settings, providers, preset-map, playwright

---
