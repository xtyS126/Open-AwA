# Tasks

## P1 高优先级任务

- [x] Task 1: 强制调用Sandbox权限检查
  - [x] SubTask 1.1: 在 `sandbox.py` 的 `execute_command` 入口处调用 `check_permission`
  - [x] SubTask 1.2: 在 `sandbox.py` 的 `execute_file_operation` 入口处调用 `check_permission`
  - [x] SubTask 1.3: 编写单元测试验证权限检查被正确调用

- [x] Task 2: 修复SQL注入风险
  - [x] SubTask 2.1: 在 `migrate_db.py` 中为列名和类型添加白名单校验
  - [x] SubTask 2.2: 使用SQLAlchemy DDL API替代原始SQL（可选）
  - [x] SubTask 2.3: 编写测试验证迁移脚本安全性

- [x] Task 3: 清理模板化注释
  - [x] SubTask 3.1: 搜索并识别所有包含"处理xxx相关逻辑"模板文本的文件
  - [x] SubTask 3.2: 清理或替换模板化docstring为有意义的注释
  - [x] SubTask 3.3: 对公共API函数补充参数和返回值说明

- [x] Task 4: 补充后端核心模块测试
  - [x] SubTask 4.1: 为 `core/agent.py` 编写单元测试
  - [x] SubTask 4.2: 为 `core/executor.py` 编写单元测试
  - [x] SubTask 4.3: 为 `api/routes/auth.py` 编写集成测试
  - [x] SubTask 4.4: 为 `api/routes/chat.py` 编写集成测试
  - [x] SubTask 4.5: 为 `security/` 模块编写安全测试
  - [x] SubTask 4.6: 为 `billing/` 模块编写单元测试
  - [x] SubTask 4.7: 为 `memory/` 模块编写单元测试

## P2 中优先级任务

- [x] Task 5: 配置数据库连接池
  - [x] SubTask 5.1: 在 `db/models.py` 的 `create_engine` 中添加连接池参数
  - [x] SubTask 5.2: 配置 `pool_size=5, max_overflow=10, pool_recycle=3600`

- [x] Task 6: 优化日志缓冲区
  - [x] SubTask 6.1: 评估日志持久化方案（数据库或文件）
  - [x] SubTask 6.2: 实现日志持久化存储
  - [x] SubTask 6.3: 为日志查询接口添加索引支持

- [x] Task 7: 修复依赖版本约束
  - [x] SubTask 7.1: 修改 `requirements.txt` 使用范围约束格式
  - [x] SubTask 7.2: 创建 `requirements-dev.txt` 分离测试依赖
  - [x] SubTask 7.3: 移除 `pytest-asyncio` 从生产依赖

- [x] Task 8: 启用ESLint严格规则
  - [x] SubTask 8.1: 在 `eslint.config.js` 中将 `no-explicit-any` 设为 `warn`
  - [x] SubTask 8.2: 逐步消除现有 `any` 类型使用

- [x] Task 9: 完善API类型定义
  - [x] SubTask 9.1: 为 `api.ts` 中的API方法定义请求/响应接口
  - [x] SubTask 9.2: 替换所有 `any` 类型为具体类型

- [x] Task 10: 修复测试文件命名
  - [x] SubTask 10.1: 重命名所有 `.test.test.tsx` 文件为 `.test.tsx`
  - [x] SubTask 10.2: 更新相关导入和引用

- [x] Task 11: 扩展覆盖率配置
  - [x] SubTask 11.1: 修改 `vitest.config.ts` 的 `coverage.include` 为 `['src/**/*.{ts,tsx}']`
  - [x] SubTask 11.2: 排除测试文件和类型声明文件

## P3 低优先级任务

- [x] Task 12: 修复数据库文件位置
  - [x] SubTask 12.1: 配置数据库路径为 `backend/` 目录下
  - [x] SubTask 12.2: 更新 `.gitignore` 排除根目录数据库文件

- [x] Task 13: 清理历史文档
  - [x] SubTask 13.1: 将 `documents/` 下的历史报告移入 `docs/archive/`
  - [x] SubTask 13.2: 清理 `.trae/specs/` 已完成的spec目录

- [x] Task 14: 移除前端辅助脚本
  - [x] SubTask 14.1: 删除 `frontend/fix_*.py` 和 `frontend/generate_tests.py` 等脚本
  - [x] SubTask 14.2: 或移动到 `scripts/` 目录

- [x] Task 15: 统一端口配置
  - [x] SubTask 15.1: 在 `vite.config.ts` 中统一端口为 5173
  - [x] SubTask 15.2: 更新 README 中的端口描述

- [x] Task 16: 清理重复导入
  - [x] SubTask 16.1: 在 `api/routes/auth.py` 中统一 User 模型导入

- [x] Task 17: 更新README目录结构
  - [x] SubTask 17.1: 更新 README 中的目录结构描述以反映实际结构

## CI/CD增强任务

- [x] Task 18: 增强CI流水线
  - [x] SubTask 18.1: 添加后端单元测试步骤 `python -m pytest`
  - [x] SubTask 18.2: 添加后端类型检查步骤（mypy或pyright）
  - [x] SubTask 18.3: 添加前端lint检查步骤 `npm run lint`
  - [x] SubTask 18.4: 添加安全扫描步骤（Bandit和npm audit）

# Task Dependencies
- [Task 1] depends on nothing.
- [Task 2] depends on nothing.
- [Task 3] depends on nothing.
- [Task 4] depends on [Task 1], [Task 2].
- [Task 5] depends on nothing.
- [Task 6] depends on nothing.
- [Task 7] depends on nothing.
- [Task 8] depends on nothing.
- [Task 9] depends on [Task 8].
- [Task 10] depends on nothing.
- [Task 11] depends on [Task 10].
- [Task 12] depends on nothing.
- [Task 13] depends on nothing.
- [Task 14] depends on nothing.
- [Task 15] depends on nothing.
- [Task 16] depends on nothing.
- [Task 17] depends on nothing.
- [Task 18] depends on [Task 4], [Task 7], [Task 8].
