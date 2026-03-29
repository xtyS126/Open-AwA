# 彻查代码 Bug Spec

## Why
项目积累了多处隐性 bug，包括运行时异常、类型不匹配、逻辑错误和不规范用法，需系统性扫描并修复，保证代码健壮性。

## What Changes
- 后端：运行 ruff/mypy/pylint 静态扫描，修复所有 ERROR 级问题
- 后端：修复 `datetime.utcnow()` 等已知 DeprecationWarning 使用
- 前端：运行 ESLint + tsc 扫描，修复所有报错
- 后端/前端：确保 pytest + vitest 全部通过

## Impact
- Affected specs: comprehensive-plugin-system, fix-terminal-errors
- Affected code: backend/（全部 .py 文件）、frontend/src/（全部 .ts/.tsx 文件）

## ADDED Requirements

### Requirement: 静态扫描零 ERROR
系统所有源码在 ruff、mypy、ESLint 检查下不得有任何 ERROR 级别输出。

#### Scenario: ruff 扫描无 error
- **WHEN** 执行 `ruff check backend/`
- **THEN** 退出码为 0，无 error 级输出

#### Scenario: mypy 扫描无 error
- **WHEN** 执行 `mypy backend/ --ignore-missing-imports`
- **THEN** 无 error 输出

#### Scenario: ESLint 扫描无 error
- **WHEN** 执行 `npx eslint src/`
- **THEN** 退出码为 0

### Requirement: 所有测试通过
修复后 pytest 109 passed，vitest 24 passed，不得引入新失败。

## MODIFIED Requirements
无

## REMOVED Requirements
无
