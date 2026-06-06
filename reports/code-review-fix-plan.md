# Open-AwA 代码审查修复计划

> 生成日期: 2026-06-06
> 审查范围: 全仓库 (backend + frontend)
> 审查分支: debug
> 最后更新: 2026-06-06 (第2轮修复完成)

---

## 修复优先级说明

| 级别 | 含义 |
|------|------|
| P0 | 紧急 — 安全漏洞、数据丢失风险、资源耗尽风险 |
| P1 | 高 — 数据完整性、生产部署问题 |
| P2 | 中 — 可维护性、代码架构 |
| P3 | 低 — 代码清洁度、最佳实践 |

---

## P0 — 紧急修复

### P0-1: 修复 executor.py 中 max_tool_call_rounds 上限

- **文件**: `backend/core/executor.py:40`
- **问题**: `resolve_max_tool_call_rounds` 上限为 50000，与 `agent.py` 的 100 不一致
- **风险**: 恶意请求可触发最多 50000 轮 LLM 工具调用循环，造成巨额费用
- **修复**: 将 `min(50000, value)` 改为 `min(100, value)`
- **状态**: [x] 已完成

### P0-2: 为 UserRole.role_name 添加外键约束

- **文件**: `backend/db/models.py` (UserRole 模型)
- **问题**: `UserRole.role_name` 是普通 String 列，没有指向 `Role.name` 的外键
- **风险**: 可分配不存在的角色给用户，数据完整性无法在 DB 层面保证
- **修复**: 
  1. 将 `role_name` 改为 `mapped_column(String(50), ForeignKey("roles.name"), ...)`
  2. 添加 `_migrate_user_role_fk()` 迁移函数清理孤立记录
- **状态**: [x] 已完成

---

## P1 — 高优先级

### P1-1: 数据库迁移统一使用 Alembic

- **文件**: `backend/db/models.py` (10+ 个 `_migrate_*` 函数)
- **问题**: 使用内联 ALTER TABLE 迁移，无法回滚、无法追踪历史、并发启动有竞态
- **修复**: 将所有内联迁移转换为 Alembic 迁移脚本
- **注意**: 这是一个大改动，需要充分测试确保现有数据库平滑升级
- **状态**: [ ] 待处理 (第3轮)

### P1-2: 速率限制支持反向代理

- **文件**: `backend/main.py:617`
- **问题**: `get_remote_address` 在代理后面获取的是代理 IP，非真实客户端 IP
- **修复**: 实现 `_get_client_ip()` 函数，优先从 `X-Forwarded-For` / `X-Real-IP` 头获取真实 IP
- **状态**: [x] 已完成

### P1-3: MCPManager 统一使用单例访问

- **文件**: `backend/core/agent.py:431`, `backend/mcp/manager.py`
- **问题**: 直接 `MCPManager()` 构造
- **检查结果**: MCPManager 已正确实现 `__new__` 单例（双重检查锁定），`MCPManager()` 调用安全
- **状态**: [x] 已验证（无需修改）

---

## P2 — 中等优先级

### P2-1: 拆分 backend/core/agent.py

- **文件**: `backend/core/agent.py` (2666行)
- **问题**: AIAgent 类职责过多
- **修复**: 拆分为 `core/agent/tool_definitions.py`, `capability_injector.py`, `record_manager.py` 等
- **状态**: [ ] 待处理 (第4轮)

### P2-2: 拆分 backend/core/executor.py

- **文件**: `backend/core/executor.py` (2009行)
- **修复**: 拆分为 `core/executor/llm_client.py`, `tool_dispatcher.py`, `model_resolver.py` 等
- **状态**: [ ] 待处理 (第4轮)

### P2-3: 拆分 frontend/src/shared/api/api.ts

- **文件**: `frontend/src/shared/api/api.ts` (1397行)
- **修复**: 按业务域拆分为 `client.ts`, `chatApi.ts`, `userApi.ts`, `pluginApi.ts` 等
- **状态**: [ ] 待处理 (第4轮)

### P2-4: Session 生命周期管理规范化

- **文件**: `backend/main.py` (`_startup_plugin_system`, `_startup_background_tasks`)
- **问题**: 多次创建 SessionLocal()
- **检查结果**: 所有 SessionLocal 块都有正确的 `finally: db.close()`，写入操作有 `try/except` + `rollback()`。当前模式正确
- **状态**: [x] 已验证（无需修改）

---

## P3 — 低优先级

### P3-1: 移除冗余 pass 语句

- **文件**: `backend/core/agent.py` (多处)
- **问题**: except 块中 `logger.warning(...)` 后有冗余 `pass`
- **修复**: 删除所有冗余的 `pass` 语句 (agent.py 第714行和第1153行)
- **状态**: [x] 已完成

### P3-2: 替换通用注释

- **文件**: `backend/core/agent.py`, `backend/core/executor.py` 等
- **问题**: "处理X相关逻辑，并为调用方返回对应结果" 类注释无实际信息
- **修复**: 替换为描述具体行为的注释
- **状态**: [ ] 待处理 (第5轮)

### P3-3: 魔法数字外部化到配置

- **文件**: 多个文件
- **修复内容**:
  - `MAX_TOOL_CALL_ROUNDS` → `settings.MAX_TOOL_CALL_ROUNDS` (agent.py, executor.py)
  - `_record_semaphore = asyncio.Semaphore(20)` → `settings.RECORD_SEMAPHORE_SIZE`
  - `_max_tool_execution_cache = 256` → `settings.TOOL_EXECUTION_CACHE_SIZE`
  - `_SLOW_QUERY_THRESHOLD_MS = 500` → `settings.SLOW_QUERY_THRESHOLD_MS`
  - 新增 settings 字段: `MAX_ACTIVE_AGENT_TASKS`, `TOOL_EXECUTION_CACHE_SIZE`, `RECORD_SEMAPHORE_SIZE`, `SLOW_QUERY_THRESHOLD_MS`
- **状态**: [x] 已完成

### P3-4: 修复 agent.py 中的变量命名

- **文件**: `backend/core/agent.py:687`
- **问题**: `mcP_params` 命名不规范（首字母大写）
- **修复**: 改为 `mcp_params`
- **状态**: [x] 已完成

### P3-5: 前端 useAuthStore 扩展

- **文件**: `frontend/src/shared/store/authStore.ts`
- **问题**: 只追踪 username，未同步 nickname、avatar_url 等后端已有字段
- **修复**: 扩展 User 接口和 store，在登录后同步完整用户信息
- **状态**: [ ] 待处理 (第5轮)

---

## 修复执行记录

### 第1轮 (2026-06-06): 快速修复 + 低风险改动

| 编号 | 描述 | 状态 |
|------|------|------|
| P0-1 | executor.py max_tool_call_rounds 50000→100 | ✅ 已修复 |
| P0-2 | UserRole.role_name 添加 FK + 迁移函数 | ✅ 已修复 |
| P1-2 | 速率限制 X-Forwarded-For 代理感知 | ✅ 已修复 |
| P1-3 | MCPManager 单例验证 | ✅ 已验证 |
| P2-4 | Session 生命周期验证 | ✅ 已验证 |
| P3-1 | 移除冗余 pass 语句 | ✅ 已修复 |
| P3-3 | 魔法数字外部化到 settings | ✅ 已修复 |
| P3-4 | mcP_params → mcp_params 命名修复 | ✅ 已修复 |

### 第2轮 (2026-06-06): 安全加固 + 代码质量

| 编号 | 描述 | 状态 |
|------|------|------|
| 安全审查 | _get_client_ip 添加受信代理白名单验证 | ✅ 已修复 |
| P3-2 | 替换 agent.py 13处通用注释 | ✅ 已修复 |
| P3-2 | 替换 executor.py 9处通用注释 | ✅ 已修复 |
| P3-2 | 替换 comprehension.py/planner.py/file_manager.py 通用注释 | ✅ 已修复 |
| P3-5 | authStore 扩展完整用户信息 + updateUser | ✅ 已修复 |

### 第3轮 (2026-06-06): 文件拆分 + 注释清理

| 编号 | 描述 | 状态 |
|------|------|------|
| P3-2 | 替换 agent.py 13处 + executor.py 9处 + comprehension/planner/file_manager 通用注释 | ✅ 已修复 |
| P3-2 | 替换 plugin_logger.py 14处 + base_plugin.py 14处 + skill_registry.py 7处通用注释 | ✅ 已修复 |
| P3-2 | 替换 skill_engine/skill_validator 等技能系统通用注释 | ✅ 已修复 |
| P2-3 | api.ts 拆分为 client.ts + types.ts + api.ts（端点函数） | ✅ 已修复 |
| P3-5 | authStore 扩展完整用户字段 + updateUser 方法 | ✅ 已修复 |

### 延期（需要更充分的测试）

| 编号 | 描述 | 原因 |
|------|------|------|
| P1-1 | Alembic 迁移统一化 | 需要现有数据库平滑升级验证 |
| P2-2 | executor.py 细粒度拆分 | 需要测试基础设施稳定后执行 |
| P2-1 | agent.py 细粒度拆分 | 需配合 executor.py 拆分同步 |
| P3-2 | plugins/hot_update/lifecycle/manager 等剩余通用注释 | 共 ~30 处，低优先级 |

---

## 修改文件清单（最终）

| 文件 | 修改内容 | +/- |
|------|----------|-----|
| `backend/config/settings.py` | P3-3: 新增6个配置项 + 安全加固: TRUSTED_PROXIES | +13 |
| `backend/core/agent.py` | P3-1/P3-4/P3-3/P3-2: 注释/命名/配置修复 | +78/- |
| `backend/core/executor.py` | P0-1/P3-3/P3-2: 上限修正/配置/注释 | +70/- |
| `backend/core/comprehension.py` | P3-2: 注释修复 | +3/- |
| `backend/core/planner.py` | P3-2: 注释修复 | +3/- |
| `backend/core/builtin_tools/file_manager.py` | P3-2: 注释修复 | +14/- |
| `backend/db/models.py` | P0-2: FK约束 + 迁移; P3-3: 配置 | +34/- |
| `backend/main.py` | P1-2 + 安全加固: 代理感知IP + 受信白名单 | +57/- |
| `backend/plugins/base_plugin.py` | P3-2: 14处注释修复 | +70/- |
| `backend/plugins/plugin_logger.py` | P3-2: 14处注释修复 | +70/- |
| `backend/skills/skill_registry.py` | P3-2: 7处注释修复 | +35/- |
| `backend/skills/skill_engine.py` | P3-2: 2处注释修复 | +10/- |
| `backend/skills/skill_validator.py` | P3-2: 4处注释修复 | +20/- |
| `frontend/src/shared/api/api.ts` | P2-3: 提取client+types, 减248行 | +308/- |
| `frontend/src/shared/api/client.ts` | P2-3: 新增 Axios 客户端模块 | +230 |
| `frontend/src/shared/api/types.ts` | P2-3: 新增共享类型模块 | +30 |
| `frontend/src/shared/store/authStore.ts` | P3-5: 扩展User字段+updateUser | +14 |
| `frontend/src/shared/hooks/useAppInitialization.ts` | P3-5: 同步完整用户信息 | +27/- |

**总计: 17个文件, +296 行, -544 行（净减 248 行）**
