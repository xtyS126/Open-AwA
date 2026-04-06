# Checklist

## P1 高优先级检查点

- [x] `sandbox.py` 的 `execute_command` 在执行前调用 `check_permission`
- [x] `sandbox.py` 的 `execute_file_operation` 在执行前调用 `check_permission`
- [x] 权限检查单元测试通过
- [x] `migrate_db.py` 使用白名单校验列名和类型
- [x] 迁移脚本安全测试通过
- [x] 所有模板化注释已清理或替换
- [x] 公共API函数有有意义的docstring
- [x] `core/agent.py` 单元测试覆盖率 >= 60%
- [x] `core/executor.py` 单元测试覆盖率 >= 60%
- [x] `api/routes/auth.py` 集成测试通过
- [x] `api/routes/chat.py` 集成测试通过
- [x] `security/` 模块安全测试通过
- [x] `billing/` 模块单元测试通过
- [x] `memory/` 模块单元测试通过
- [x] 后端整体测试覆盖率 >= 60%

## P2 中优先级检查点

- [x] `db/models.py` 配置了连接池参数
- [x] 日志持久化到数据库或文件
- [x] 日志查询接口有索引支持
- [x] `requirements.txt` 使用范围约束格式
- [x] `requirements-dev.txt` 包含测试依赖
- [x] `pytest-asyncio` 已从生产依赖移除
- [x] `eslint.config.js` 中 `no-explicit-any` 设为 `warn`
- [x] 前端 `any` 类型使用数量减少
- [x] `api.ts` 所有API方法有明确类型定义
- [x] 无 `.test.test.tsx` 双重后缀文件
- [x] `vitest.config.ts` 覆盖率配置包含所有源文件

## P3 低优先级检查点

- [x] 数据库文件位于 `backend/` 目录下
- [x] `.gitignore` 正确排除数据库文件
- [x] 历史报告已归档到 `docs/archive/`
- [x] `.trae/specs/` 已清理完成的spec
- [x] 前端辅助脚本已移除或移动到 `scripts/`
- [x] 端口配置在所有文件中一致
- [x] `api/routes/auth.py` 无重复导入
- [x] README目录结构与实际一致

## CI/CD检查点

- [x] CI包含后端单元测试步骤
- [x] CI包含后端类型检查步骤
- [x] CI包含前端lint检查步骤
- [x] CI包含安全扫描步骤
- [x] CI流水线全部通过

## 最终验证

- [x] 所有单元测试通过
- [x] 所有集成测试通过
- [x] 代码覆盖率达标
- [x] 无新增安全漏洞
- [x] 代码符合项目编码规范
