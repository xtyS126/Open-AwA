# Checklist

## 后端
- [x] `ruff check backend/` 退出码为 0，无 error
- [x] `mypy backend/ --ignore-missing-imports` 无 error（从 198 降至 0）
- [x] `datetime.utcnow()` 已全部替换为 `datetime.now(timezone.utc)`
- [x] `python -m pytest` 全部 passed（109 passed）

## 前端
- [x] `npx eslint src/` 无 error 级输出
- [x] `npm run typecheck` 0 errors
- [x] `npm run test` 全部 passed（24 passed）

## 逻辑审查
- [x] 所有 API 路由有异常处理（try/except 或 HTTPException）
- [x] 插件核心逻辑边界条件（None/空列表）已处理
- [x] 前端 API 调用均有 catch 错误处理
- [x] 前端组件均有加载中与错误状态展示

## 提交
- [x] git commit 仅包含源码变更
- [x] 提交信息符合 Conventional Commits 规范
