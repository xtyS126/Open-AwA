# P0 Security Vulnerabilities Fix Spec

## Why
代码审查报告指出后端存在4个P0级严重安全漏洞：命令注入、路径遍历、动态代码执行风险、危险命令白名单。虽然当前代码已包含部分安全措施，但需要验证修复完整性并补充安全测试，确保沙箱机制真正有效。

## What Changes
- 验证 `sandbox.py` 命令注入修复：确认使用 `create_subprocess_exec` 而非 `create_subprocess_shell`，且命令白名单不包含危险命令
- 验证 `skill_executor.py` Shell 命令白名单：确认已移除 `rm`、`chmod`、`chown`、`xargs` 等高危命令
- 验证路径遍历防护：确认 `_validate_path` 和 `_validate_file_path` 函数正确限制文件操作范围
- 验证 `exec()` 安全策略：确认 `CodeValidator` 已移除 `FunctionDef` 和 `getattr`
- 补充安全单元测试：为 sandbox.py 和 skill_executor.py 编写安全测试用例
- 统一路径校验逻辑：提取公共路径校验函数，避免重复实现

## Impact
- Affected specs: 安全沙箱机制、技能执行系统
- Affected code:
  - `backend/security/sandbox.py`
  - `backend/skills/skill_executor.py`
  - `backend/tests/test_sandbox_security.py` (新增)
  - `backend/tests/test_skill_executor_security.py` (新增)

## ADDED Requirements

### Requirement: Command Execution Security
系统 SHALL 使用 `create_subprocess_exec` 执行命令，禁止使用 `create_subprocess_shell`。

#### Scenario: Shell Injection Prevention
- **WHEN** 攻击者尝试注入 Shell 命令（如 `ls; rm -rf /`）
- **THEN** 系统拒绝执行，返回权限错误

#### Scenario: Command Whitelist Enforcement
- **WHEN** 执行命令不在白名单内
- **THEN** 系统拒绝执行，返回 "命令不在允许列表中" 错误

### Requirement: Path Traversal Prevention
系统 SHALL 限制文件操作在指定工作目录内。

#### Scenario: Path Traversal Attack Prevention
- **WHEN** 攻击者尝试访问工作目录外的文件（如 `../../../etc/passwd`）
- **THEN** 系统拒绝操作，返回 "文件路径超出允许范围" 错误

#### Scenario: Sensitive Path Protection
- **WHEN** 尝试访问敏感路径（如 `/etc/`、`/root/`、`.env`）
- **THEN** 系统拒绝操作，返回路径校验失败错误

### Requirement: Code Execution Sandbox
系统 SHALL 限制动态代码执行的 AST 节点类型和内置函数。

#### Scenario: Dangerous Function Blocking
- **WHEN** 代码尝试调用 `exec`、`eval`、`__import__`、`getattr` 等危险函数
- **THEN** 系统拒绝执行，返回 "禁止调用函数" 错误

#### Scenario: Function Definition Blocking
- **WHEN** 代码包含 `def` 或 `async def` 函数定义
- **THEN** 系统拒绝执行，返回 "不支持的代码结构" 错误

### Requirement: Security Test Coverage
系统 SHALL 为安全模块提供单元测试覆盖。

#### Scenario: Sandbox Security Tests
- **WHEN** 运行 `pytest backend/tests/test_sandbox_security.py`
- **THEN** 所有测试通过，覆盖命令注入、路径遍历、权限检查场景

## MODIFIED Requirements

### Requirement: Unified Path Validation
- **WHEN** 多个模块需要路径校验
- **THEN** 它们 SHALL 使用统一的路径校验函数，避免重复实现

## REMOVED Requirements
无移除的需求。
