# Open-AwA 代码健壮性审计报告

> 审计日期：2026-04-29
> 审计范围：全部后端 (Python/FastAPI) 及前端 (TypeScript/React) 代码
> 审计方法：5组并行代理，静态分析全部源代码文件

## 总览

| 风险等级 | 数量 | 说明 |
|----------|------|------|
| Critical | 15  | 可导致服务崩溃、安全漏洞或数据泄露 |
| High     | 38  | 可导致功能异常、资源泄漏或性能问题 |
| Medium   | 58  | 潜在风险，需在特定条件下触发 |
| Low      | 36  | 代码质量问题，建议改进 |
| **合计** | **147** | |

---

## 一、Critical 级问题 (15项)

### 安全类 (6项)

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| C1 | `backend/core/executor.py` | 命令超时时子进程未被 kill，僵尸进程泄漏 | ~1193 |
| C2 | `backend/core/executor.py` | 文件读取无路径遍历防护，可读取 `/etc/passwd` 等 | ~1147 |
| C3 | `backend/core/executor.py` | 使用 `create_subprocess_shell` 存在命令注入风险 | ~1175 |
| C4 | `backend/skills/built_in/terminal_executor.py` | 使用 `create_subprocess_shell` + 黑名单过滤不足 | ~120 |
| C5 | `backend/workflow/engine.py` | 使用 `eval()` 执行用户输入，代码注入风险 | ~326 |
| C6 | `backend/mcp/transport.py` | 环境变量明文传递给子进程，可能泄露 API key | ~90 |

### 数据完整性类 (5项)

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| C7 | `backend/billing/budget_manager.py` | `update_budget` 使用无限定 `setattr`，可覆盖任意字段 | ~102 |
| C8 | `backend/billing/pricing_manager.py` | `update_pricing` 使用无限定 `setattr` | ~427 |
| C9 | `backend/billing/pricing_manager.py` | `update_configuration` 同样存在无限定 `setattr` | ~813 |

### 内存/性能类 (4项)

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| C10 | `backend/api/routes/tools.py` | 所有端点调用 `execute_tool` 无 try-catch | ~76-222 |
| C11 | `backend/api/routes/chat.py` | Agent 核心处理 `agent.process()` 无 try-catch | ~104 |
| C12 | `backend/api/routes/behavior.py` | 全量加载 LLM 调用记录到内存，无 `.limit()` | ~87 |
| C13 | `backend/api/routes/behavior.py` | 全量加载 tool_usage 和 intent 详情，无限制 | ~55-76 |

### 前端类 (2项)

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| C14 | `frontend/src/shared/utils/logger.ts` | `localStorage.getItem` 直接访问无 try-catch | ~28 |
| C15 | `frontend/src/shared/utils/logger.ts` | `sessionStorage.setItem/getItem` 直接访问无 try-catch | ~52,56 |

---

## 二、High 级问题 (38项)

### 后端 API 路由层

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| H1 | `backend/api/routes/chat.py` | 文件上传 I/O 无 try-catch | ~382 |
| H2 | `backend/api/routes/models.py` | LiteLLM 外部 API 调用无 try-catch | ~25-79 |
| H3 | `backend/api/routes/prompts.py` | 提示词激活存在读-改-写竞态条件 | ~42-71 |
| H4 | `backend/api/routes/behavior.py` | `log_behavior` 端点无输入验证 (action_type/details) | ~188 |
| H5 | `backend/api/routes/behavior.py` | DB commit 无 try-catch/rollback | ~204 |
| H6 | `backend/api/routes/skills.py` | 经验提取无 try-catch | ~1352 |
| H7 | `backend/api/routes/conversation.py` | session_id 无输入验证 | ~174 |
| H8 | `backend/api/routes/workflows.py` | 工作流解析无 try-catch | ~50 |

### 后端核心引擎

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| H9 | `backend/core/executor.py` | 每次调用新建 PluginManager，资源浪费 | ~1026 |
| H10 | `backend/core/executor.py` | `load_plugin` 返回值未检查 | ~1029 |
| H11 | `backend/core/litellm_adapter.py` | 熔断器创建存在竞态条件 | ~160 |
| H12 | `backend/core/litellm_adapter.py` | 非可重试错误被双重计数失败 | ~534 |
| H13 | `backend/core/feedback.py` | `_record_hook` 回调崩溃会中断主流程 | ~66 |
| H14 | `backend/core/agent.py` | `_schedule_record` 调用数十次无 try-catch | ~820-904 |
| H15 | `backend/core/agent.py` | `_record_hook` 可能崩溃主流程 | ~144 |
| H16 | `backend/core/scheduled_task_manager.py` | 后台任务持有 DB session 可能已被关闭 | ~238 |
| H17 | `backend/core/subagent.py` | 条件边回调崩溃会中断整个图执行 | ~194 |
| H18 | `backend/core/planner.py` | `_extract_task_steps` 缺少 dict key 检查 | ~223 |
| H19 | `backend/core/behavior_logger.py` | 缺少 dict key 检查 | ~183 |

### 后端插件/记忆/技能/计费/安全

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| H20 | `backend/billing/calculator.py` | `_apply_model_rules` 缺少 null-check | ~多处 |
| H21 | `backend/skills/built_in/web_search.py` | HTTPS 连接异常路径未关闭 | ~137 |
| H22 | `backend/memory/working_memory.py` | OrderedDict 操作无锁保护, 并发不安全 | ~全类 |
| H23 | `backend/memory/experience_manager.py` | `get_experience_stats` 全量加载到内存 | ~549 |
| H24 | `backend/memory/manager.py` | `get_memory_stats` 全量加载到内存 | ~509 |

### 后端基础设施

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| H25 | `backend/api/schemas.py` | `AttachmentItem.data` 无 max_length | ~63 |
| H26 | `backend/api/schemas.py` | `UserCreate.password` 无 min_length | ~24 |
| H27 | `backend/api/dependencies.py` | 缺少 null/disabled 检查 | ~128 |
| H28 | `backend/mcp/manager.py` | `remove_server` 未调用 disconnect | ~74 |
| H29 | `backend/mcp/manager.py` | `rollback_to_snapshot` 清除客户端未 disconnect | ~296 |
| H30 | `backend/main.py` | DB 初始化无 try-catch | ~101-104 |
| H31 | `backend/main.py` | 静态文件服务缺少路径遍历保护 | ~410 |
| H32 | `backend/config/security.py` | token 黑名单添加存在竞态条件 | ~26 |
| H33 | `backend/db/models.py` | 迁移脚本全量加载 ConversationRecord | ~797 |

### 前端

| # | 文件 | 问题 | 行号 |
|---|------|------|------|
| H34 | `frontend/src/features/chat/store/chatStore.ts` | Zustand store 直接修改数组元素(破坏不可变性) | ~95 |
| H35 | `frontend/src/shared/api/api.ts` | API 客户端多处使用 `any` 类型 | ~229-624 |
| H36 | `frontend/src/shared/utils/logger.ts` | sessionStorage 直接访问(与 C15 相关) | ~52,56 |

---

## 三、正向发现 (代码库优势)

审计中也发现了许多做得好的实践：

1. **无 SQL 注入风险** — 所有数据库操作使用 SQLAlchemy ORM 参数化查询
2. **无硬编码密钥** — 密钥通过 `SecretStr` 和环境变量管理
3. **完整的错误边界覆盖** — 前端所有路由都包裹在 `<ErrorBoundary>` 中
4. **路径遍历防护良好** — `experience_files.py` 和 `logs.py` 中有完善的 real-path 校验
5. **ZIP 炸弹防护** — `plugin_manager.py` 中正确实现了 ZIP 解压安全校验
6. **SSRF 防护** — `web_search.py` 中检查 IP 地址防止内网访问
7. **DNS 重绑定防护** — `plugin_manager.py` 中实现双重 DNS 解析
8. **XSS 防护** — 无 `dangerouslySetInnerHTML` 使用，ReactMarkdown 配置安全
9. **全局 Promise 异常处理** — 前端注册了 `unhandledrejection` 事件处理器
10. **安全沙箱执行** — `security/sandbox.py` 正确使用 `shell=False` 和路径校验
11. **登录频率限制** — 使用正确的锁机制和 TTL 清理
12. **AST 白名单** — `skill_executor.py` 使用 AST 白名单安全执行代码

---

## 四、修复优先级建议

### 第1批 (必须立即修复 - Critical)
1. C5 — `eval()` 代码执行 (workflow/engine.py)
2. C1-C3 — 命令执行安全 (executor.py)
3. C4 — 终端 shell 注入 (terminal_executor.py)
4. C6 — MCP 环境变量泄露 (mcp/transport.py)
5. C7-C9 — 无限定 setattr (billing)
6. C10-C11 — 核心处理缺失 try-catch (chat.py, tools.py)
7. C14-C15 — 前端 localStorage 崩溃 (logger.ts)

### 第2批 (应尽快修复 - High)
8. H3 — 提示词激活竞态条件 (prompts.py)
9. H11-H12 — 熔断器竞态 (litellm_adapter.py)
10. H28-H29 — MCP 资源泄漏 (mcp/manager.py)
11. H22 — 内存存储线程安全 (working_memory.py)
12. H23-H24 — 无限制内存加载 (memory manager)
13. H33 — 迁移脚本 OOM 风险 (db/models.py)
14. H34 — 前端不可变性问题 (chatStore.ts)

### 第3批 (常规修复 - Medium)
计费模型验证、MCP/WF 相关中等风险、前端类型安全等 58 项
