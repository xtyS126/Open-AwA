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

## [LRN-20260704-004] best_practice

**Logged**: 2026-07-04T20:56:25+08:00
**Priority**: high
**Status**: resolved
**Area**: tests

### Summary
FastAPI 路由单测覆盖依赖后，`with TestClient(main.app)` 仍会运行真实 lifespan 并访问默认数据库。

### Details
`app.dependency_overrides[get_db]` 只影响路由依赖注入，不会替换 `main.py` 启动阶段直接调用的 `init_db()` 与模块级 SQLAlchemy engine。只验证路由契约的测试若使用 TestClient 上下文管理器，会在进入上下文时运行 lifespan，可能污染或写入用户数据库。

### Suggested Action
路由契约测试使用不启动 lifespan 的客户端生命周期；确需验证启动流程时，必须在导入 `main.app` 前绑定独立临时数据库，并验证没有回落到默认数据库。

### Metadata
- Source: error
- Related Files: backend/tests/test_api_route_regressions.py, backend/tests/test_api_skills_weixin.py, backend/main.py
- Tags: pytest, fastapi, lifespan, sqlite, isolation

### Resolution
- **Resolved**: 2026-07-04T21:05:00+08:00
- **Notes**: conftest 在测试收集前绑定独立数据库，并在每个用例 fixture 设置前清空全局依赖覆盖。

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

## [LRN-20260504-003] best_practice

**Logged**: 2026-05-04T10:40:00+08:00
**Priority**: high
**Status**: resolved
**Area**: tests

### Summary
本项目运行后端 pytest 时需要以 `backend` 作为工作目录，或显式补齐 `PYTHONPATH`，否则测试收集阶段会找不到 `api`、`db`、`core` 包。

### Details
在仓库根目录直接执行 `pytest backend/tests/test_task_runtime_api.py ...` 时，pytest 收集阶段出现 `ModuleNotFoundError: No module named 'api'`、`No module named 'db'`、`No module named 'core'`。原因是项目中的后端测试默认依赖 `backend` 目录作为 Python 导入根，而不是仓库根目录。切换到 `d:\代码\Open-AwA\backend` 后再执行同类测试命令，可正常按包路径导入。

### Suggested Action
执行后端测试时优先使用 `cwd=backend`，命令写成 `pytest tests/<file>.py`；如果必须在仓库根目录执行，则先设置等效的 `PYTHONPATH=backend`。后续新增后端测试文件时，也应尽量沿用已有测试文件中的导入方式和工作目录约定。

### Metadata
- Source: error
- Related Files: backend/tests/test_task_runtime_api.py, backend/tests/test_task_runtime_phase1.py, backend/tests/test_task_runtime_phase2.py, backend/tests/test_task_runtime_phase3.py, backend/tests/test_task_runtime_phase4.py
- Tags: pytest, backend, pythonpath, windows, task-runtime

---
