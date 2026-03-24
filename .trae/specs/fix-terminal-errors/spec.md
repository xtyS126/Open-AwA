# 修复 Terminal 报错 Spec

## Why
Terminal#1-231 存在报错，需要定位并修复源码中的真实错误，确保 pytest、typecheck、test 全部通过后提交 git。

## What Changes
- 修复后端 pytest 报错
- 修复前端 typecheck/test 报错
- 提交 git

## Impact
- Affected specs: comprehensive-plugin-system（依赖干净的测试环境）
- Affected code: backend/billing/pricing_manager.py、frontend/package.json 及相关测试文件

## ADDED Requirements

### Requirement: 所有测试通过
系统必须确保后端 pytest、前端 typecheck 与 test 全部通过后方可提交 git。

#### Scenario: pytest 失败时阻断提交
- **WHEN** `python -m pytest` 返回非零退出码
- **THEN** 不得执行 git commit，需先修复失败用例

#### Scenario: 前端测试失败时阻断提交
- **WHEN** `npm run typecheck` 或 `npm run test` 返回非零退出码
- **THEN** 不得执行 git commit，需先修复失败用例

## MODIFIED Requirements
无

## REMOVED Requirements
无
