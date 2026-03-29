# Tasks

- [x] Task 1: 后端静态扫描与修复
  - [x] SubTask 1.1: 运行 `ruff check backend/ --select E,F --fix`，记录无法自动修复的问题
  - [x] SubTask 1.2: 运行 `mypy backend/ --ignore-missing-imports`，修复所有 error
  - [x] SubTask 1.3: 修复所有 `datetime.utcnow()` 改为 `datetime.now(timezone.utc)`
  - [x] SubTask 1.4: 运行 `python -m pytest` 确认 109 passed

- [x] Task 2: 前端静态扫描与修复
  - [x] SubTask 2.1: 运行 `npx eslint src/ --ext .ts,.tsx`，修复所有 error 级问题
  - [x] SubTask 2.2: 运行 `npm run typecheck`，修复所有 tsc error
  - [x] SubTask 2.3: 运行 `npm run test`，确认 24 passed

- [x] Task 3: 逻辑 bug 人工审查与修复
  - [x] SubTask 3.1: 审查 backend/api/routes/ 下所有路由，检查异常处理缺失
  - [x] SubTask 3.2: 审查 backend/plugins/ 核心逻辑，检查边界条件（None/空列表/负数）
  - [x] SubTask 3.3: 审查 frontend/src/services/ API 调用，检查错误处理缺失
  - [x] SubTask 3.4: 审查 frontend/src/pages/ 组件，检查未处理的加载/错误状态

- [x] Task 4: 回归验证与提交
  - [x] SubTask 4.1: `python -m pytest` → 全部 passed
  - [x] SubTask 4.2: `npm run typecheck` + `npm run test` → 全部通过
  - [x] SubTask 4.3: `git add` 仅源码文件，`git commit -m "fix: 彻查并修复代码 bug"`

# Task Dependencies
- Task 2 可与 Task 1 并行
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 3
