# Comprehensive Code Review Issues Fix Spec

## Why
代码审查报告指出项目存在24个问题，其中P0安全漏洞已修复，但仍有5个P1高优先级问题、8个P2中优先级问题和7个P3低优先级问题待修复。这些问题涉及安全性、代码质量、测试覆盖率、性能优化、依赖管理和项目结构等多个维度，需要系统性修复以确保代码质量符合项目标准。

## What Changes
- **P1修复**: Sandbox权限检查强制调用、SQL注入风险修复、注释质量清理、后端测试覆盖率提升
- **P2修复**: 数据库连接池配置、日志缓冲区优化、依赖版本约束、ESLint规则启用、API类型定义、测试文件命名、覆盖率配置扩展
- **P3修复**: 数据库文件位置、目录清理、辅助脚本移除、端口配置统一、重复导入清理、README更新
- **CI/CD增强**: 后端测试步骤、类型检查、lint检查、安全扫描

## Impact
- Affected specs: 安全模块、测试体系、依赖管理、CI/CD流水线
- Affected code:
  - `backend/security/sandbox.py`
  - `backend/migrate_db.py`
  - `backend/db/models.py`
  - `backend/config/logging.py`
  - `backend/requirements.txt`
  - `backend/api/routes/auth.py`
  - `frontend/eslint.config.js`
  - `frontend/vitest.config.ts`
  - `frontend/src/shared/api/api.ts`
  - `frontend/src/__tests__/` 目录
  - `.github/workflows/ci.yml`
  - `README.md`

## ADDED Requirements

### Requirement: Sandbox Permission Enforcement
系统 SHALL 在执行命令和文件操作前强制调用权限检查。

#### Scenario: Command Execution Permission Check
- **WHEN** 调用 `execute_command` 方法
- **THEN** 系统 SHALL 先调用 `check_permission` 验证权限，拒绝未授权操作

#### Scenario: File Operation Permission Check
- **WHEN** 调用 `execute_file_operation` 方法
- **THEN** 系统 SHALL 先调用 `check_permission` 验证权限，拒绝未授权操作

### Requirement: SQL Injection Prevention in Migration
迁移脚本 SHALL 使用安全的DDL执行方式。

#### Scenario: Safe DDL Execution
- **WHEN** 执行数据库迁移
- **THEN** 系统 SHALL 使用白名单校验或SQLAlchemy DDL API，禁止f-string拼接

### Requirement: Backend Test Coverage
后端核心模块 SHALL 具备单元测试覆盖。

#### Scenario: Core Module Tests
- **WHEN** 运行 `pytest backend/tests/`
- **THEN** 覆盖率 SHALL >= 60%，核心模块（core/、api/routes/、security/）均有测试

### Requirement: Database Connection Pool
数据库连接 SHALL 使用连接池配置。

#### Scenario: Connection Pool Configuration
- **WHEN** 创建数据库引擎
- **THEN** 系统 SHALL 配置 `pool_size`、`max_overflow`、`pool_recycle` 参数

### Requirement: Dependency Version Constraints
依赖版本 SHALL 使用范围约束而非开放下限。

#### Scenario: Version Constraint Format
- **WHEN** 定义依赖版本
- **THEN** 系统 SHALL 使用 `~=` 或 `>=x.y,<x+1.0` 格式限制主版本

### Requirement: Test Dependency Separation
测试依赖 SHALL 与生产依赖分离。

#### Scenario: Requirements Separation
- **WHEN** 安装生产依赖
- **THEN** 系统 SHALL 不包含 `pytest-asyncio` 等测试工具

### Requirement: ESLint Strict Mode
前端代码 SHALL 启用严格ESLint规则。

#### Scenario: No Explicit Any
- **WHEN** 使用 `any` 类型
- **THEN** ESLint SHALL 报告警告，逐步消除 `any` 使用

### Requirement: API Type Safety
前端API层 SHALL 使用严格类型定义。

#### Scenario: Typed API Methods
- **WHEN** 调用API方法
- **THEN** 参数和返回值 SHALL 有明确的TypeScript接口定义

### Requirement: Test File Naming Convention
测试文件 SHALL 使用统一命名规范。

#### Scenario: Single Test Suffix
- **WHEN** 创建测试文件
- **THEN** 文件名 SHALL 使用 `.test.tsx` 或 `.spec.tsx` 单一后缀

### Requirement: Coverage Configuration Scope
覆盖率配置 SHALL 包含所有源文件。

#### Scenario: Full Coverage Scope
- **WHEN** 运行覆盖率测试
- **THEN** 统计范围 SHALL 包含 `src/**/*.{ts,tsx}` 所有源文件

### Requirement: CI Backend Testing
CI流水线 SHALL 包含后端测试步骤。

#### Scenario: Backend Test Step
- **WHEN** CI运行
- **THEN** 流水线 SHALL 执行 `python -m pytest` 并检查覆盖率

### Requirement: CI Type Checking
CI流水线 SHALL 包含类型检查步骤。

#### Scenario: Type Check Step
- **WHEN** CI运行
- **THEN** 流水线 SHALL 执行 mypy 或 pyright 检查

### Requirement: CI Security Scanning
CI流水线 SHALL 包含安全扫描步骤。

#### Scenario: Security Scan Step
- **WHEN** CI运行
- **THEN** 流水线 SHALL 执行 Bandit 和 npm audit 扫描

## MODIFIED Requirements

### Requirement: Code Comments Quality
- **WHEN** 编写函数注释
- **THEN** 注释 SHALL 描述实际业务逻辑，禁止使用模板化文本

### Requirement: Database File Location
- **WHEN** 数据库文件创建
- **THEN** 文件 SHALL 位于 `backend/` 目录下，并在 `.gitignore` 中正确排除

### Requirement: Port Configuration Consistency
- **WHEN** 配置开发服务器端口
- **THEN** `vite.config.ts`、`package.json` 和 `README.md` SHALL 使用一致的端口值

### Requirement: README Directory Structure
- **WHEN** README描述项目结构
- **THEN** 描述 SHALL 与实际目录结构一致

## REMOVED Requirements
无移除的需求。
