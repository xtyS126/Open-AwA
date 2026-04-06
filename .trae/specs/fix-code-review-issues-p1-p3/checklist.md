# Checklist

## P1 高优先级检查点

- [ ] `sandbox.py` 的 `execute_command` 在执行前调用 `check_permission`
- [ ] `sandbox.py` 的 `execute_file_operation` 在执行前调用 `check_permission`
- [ ] 权限检查单元测试通过
- [ ] `migrate_db.py` 使用白名单校验列名和类型
- [ ] 迁移脚本安全测试通过
- [ ] 所有模板化注释已清理或替换
- [ ] 公共API函数有有意义的docstring
- [ ] `core/agent.py` 单元测试覆盖率 >= 60%
- [ ] `core/executor.py` 单元测试覆盖率 >= 60%
- [ ] `api/routes/auth.py` 集成测试通过
- [ ] `api/routes/chat.py` 集成测试通过
- [ ] `security/` 模块安全测试通过
- [ ] `billing/` 模块单元测试通过
- [ ] `memory/` 模块单元测试通过
- [ ] 后端整体测试覆盖率 >= 60%

## P2 中优先级检查点

- [ ] `db/models.py` 配置了连接池参数
- [ ] 日志持久化到数据库或文件
- [ ] 日志查询接口有索引支持
- [ ] `requirements.txt` 使用范围约束格式
- [ ] `requirements-dev.txt` 包含测试依赖
- [ ] `pytest-asyncio` 已从生产依赖移除
- [ ] `eslint.config.js` 中 `no-explicit-any` 设为 `warn`
- [ ] 前端 `any` 类型使用数量减少
- [ ] `api.ts` 所有API方法有明确类型定义
- [ ] 无 `.test.test.tsx` 双重后缀文件
- [ ] `vitest.config.ts` 覆盖率配置包含所有源文件

## P3 低优先级检查点

- [ ] 数据库文件位于 `backend/` 目录下
- [ ] `.gitignore` 正确排除数据库文件
- [ ] 历史报告已归档到 `docs/archive/`
- [ ] `.trae/specs/` 已清理完成的spec
- [ ] 前端辅助脚本已移除或移动到 `scripts/`
- [ ] 端口配置在所有文件中一致
- [ ] `api/routes/auth.py` 无重复导入
- [ ] README目录结构与实际一致

## CI/CD检查点

- [ ] CI包含后端单元测试步骤
- [ ] CI包含后端类型检查步骤
- [ ] CI包含前端lint检查步骤
- [ ] CI包含安全扫描步骤
- [ ] CI流水线全部通过

## 最终验证

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 代码覆盖率达标
- [ ] 无新增安全漏洞
- [ ] 代码符合项目编码规范
