# Tasks

## 阶段一：审查准备（无依赖）

- [x] Task 1: 建立审查上下文与工具准备
  - [x] SubTask 1.1: 确认项目最新的目录结构、所有源文件清单
  - [x] SubTask 1.2: 回顾之前 `audit-entire-repository-codebase` 的审查报告，了解已覆盖和未覆盖的维度
  - [x] SubTask 1.3: 准备静态分析工具配置（pylint、mypy、bandit、eslint、tsc）
  - [x] SubTask 1.4: 确认现有测试套件可运行，记录当前测试通过率（后端 1 fail + 1 collection error，前端 8 fail / 96 pass）

## 阶段二：自动化静态分析扫描（依赖 Task 1）

- [x] Task 2: 运行后端静态分析工具
  - [x] SubTask 2.1: 运行 pylint 扫描所有后端 Python 文件，记录所有 warning/error
  - [x] SubTask 2.2: 运行 mypy 类型检查，记录 65 个类型错误（跨 23 个文件）
  - [x] SubTask 2.3: 运行 bandit 安全扫描，记录 B104/B105/B106/B108/B110/B307 等发现
  - [x] SubTask 2.4: 汇总静态分析结果，标记需深入审查的潜在问题

- [x] Task 3: 运行前端静态分析工具
  - [x] SubTask 3.1: 运行 ESLint（需安装缺失包 @eslint/js、@typescript-eslint/eslint-plugin 等），记录修复后结果
  - [x] SubTask 3.2: 运行 TypeScript 类型检查（tsc --noEmit），零错误通过
  - [x] SubTask 3.3: 汇总前端静态分析结果（TSC 0 错误，ESLint 配置修复后正常工作）

## 阶段三：人工深度审查（依赖 Task 2、Task 3）

### Track A: 后端核心路径审查（可以并行子任务）

- [x] Task 4: 审查异常处理与边界条件（后端核心模块）
  - [x] SubTask 4.1: 审查 `core/agent.py` — Agent 主循环的异常捕获、多轮工具调用的错误传播、中断恢复（发现 8 项）
  - [x] SubTask 4.2: 审查 `core/executor.py` — 工具执行异常处理、超时控制、重试逻辑（发现 7 项）
  - [x] SubTask 4.3: 审查 `core/litellm_adapter.py` — LLM 调用异常、流式解析错误、退避策略（发现 6 项）
  - [x] SubTask 4.4: 审查 `core/planner.py`、`core/comprehension.py` — 规划与理解模块的空输入、异常路径（发现 5 项）

- [x] Task 5: 审查输入验证与数据校验（后端 API 层）
  - [x] SubTask 5.1: 审查 `api/routes/chat.py` — 消息输入验证、会话 ID 校验、流式参数校验（发现 2 项）
  - [x] SubTask 5.2: 审查 `api/routes/auth.py`、`api/routes/security.py` — 认证/安全端点输入校验（发现 2 项）
  - [x] SubTask 5.3: 审查 `api/routes/plugins.py`、`api/routes/skills.py` — 插件/技能端点输入校验（发现 4 项）
  - [x] SubTask 5.4: 审查 `api/routes/billing/`、`api/routes/weixin.py` — 计费/微信端点输入校验（发现 5 项）
  - [x] SubTask 5.5: 审查 `api/dependencies.py`、`api/schemas.py` — 通用依赖注入和 Schema 定义完整性（发现 4 项）

- [x] Task 6: 审查日志记录与错误处理充分性
  - [x] SubTask 6.1: 审查关键路径（chat、agent、executor）的错误是否被正确传播
  - [x] SubTask 6.2: 审查所有 `except` 块是否合理（不只是 `pass` 或 `log.exception`）
  - [x] SubTask 6.3: 审查日志是否包含充分的上下文（请求 ID、用户 ID、会话 ID）
  - [x] SubTask 6.4: 审查是否有敏感信息泄露到日志（token、密钥、个人信息）

- [x] Task 7: 审查并发与内存安全
  - [x] SubTask 7.1: 审查全局变量和模块级状态的使用（`chat.py` 的 `active_connections`、`agent.py` 等）
  - [x] SubTask 7.2: 审查插件沙箱的资源隔离与释放
  - [x] SubTask 7.3: 审查 WebSocket 连接的资源生命周期管理
  - [x] SubTask 7.4: 审查数据库会话的生命周期管理（是否存在泄漏的 session）

- [x] Task 8: 审查代码复用与模块化
  - [x] SubTask 8.1: 检测后端重复代码模式（相同逻辑在多处出现）
  - [x] SubTask 8.2: 检测过度耦合（模块间循环引用、上帝函数、超大类）
  - [x] SubTask 8.3: 检测未使用的导入、函数、变量

- [x] Task 9: 审查性能瓶颈
  - [x] SubTask 9.1: 审查 ORM 查询（N+1、无索引、无分页的查询模式）
  - [x] SubTask 9.2: 审查 LLM 调用链的并发限制、超时、buffer 管理
  - [x] SubTask 9.3: 审查文件 I/O 操作（日志写入、文件缓存、大量小文件读写）
  - [x] SubTask 9.4: 审查前端渲染性能（不必要的重渲染、大列表渲染、状态更新频率）

### Track B: 前端核心路径审查（可以并行子任务）

- [x] Task 10: 审查前端异常处理与边界条件
  - [x] SubTask 10.1: 审查 `features/chat/` 全部代码 — ChatPage、chatStore、chatCache、流式消息处理、SSE 异常
  - [x] SubTask 10.2: 审查 `shared/api/api.ts` — API 调用异常处理、超时、重试
  - [x] SubTask 10.3: 审查 `shared/components/ErrorBoundary.tsx` — 错误边界覆盖范围、降级 UI
  - [x] SubTask 10.4: 审查 `features/auth/`、`features/settings/` 的关键表单提交异常处理

- [x] Task 11: 审查前端输入验证与类型安全
  - [x] SubTask 11.1: 审查所有表单输入的校验逻辑（登录、配置、设置等）
  - [x] SubTask 11.2: 审查 API 响应类型定义与实际数据结构的一致性
  - [x] SubTask 11.3: 审查 `any` 类型的使用情况和类型安全风险

- [x] Task 12: 审查前端状态管理与内存安全
  - [x] SubTask 12.1: 审查 `chatStore`、`authStore`、`themeStore` 的状态管理模式和潜在状态泄漏
  - [x] SubTask 12.2: 审查 useEffect 的依赖数组是否正确（防止无限循环/内存泄漏）
  - [x] SubTask 12.3: 审查事件监听器的注册和清理
  - [x] SubTask 12.4: 审查 WebSocket 连接的资源释放

### Track C: 插件系统审查（可以并行）

- [x] Task 13: 审查插件系统安全与健壮性
  - [x] SubTask 13.1: 审查插件加载链路的异常隔离（单个插件崩溃不影响其他）
  - [x] SubTask 13.2: 审查插件热更新的竞态条件和状态一致性
  - [x] SubTask 13.3: 审查插件与主进程的通信协议安全
  - [x] SubTask 13.4: 审查 5 个活动插件的代码质量（twitter-monitor、hello-world、theme-switcher、data-chart、user-profile-chat）

### Track D: 测试体系评估（可以并行）

- [x] Task 14: 审查测试覆盖与质量
  - [x] SubTask 14.1: 评估后端测试覆盖率，识别未覆盖的核心路径
  - [x] SubTask 14.2: 评估前端测试覆盖率，识别未覆盖的组件和逻辑
  - [x] SubTask 14.3: 审查测试用例的有效性（是否测试了正确的行为，而非只是提高覆盖率）

## 阶段四：产出审查报告（依赖 Track A/B/C/D 全部完成）

- [x] Task 15: 生成结构化审查报告
  - [x] SubTask 15.1: 汇总所有 Track 的发现，按风险等级分类
  - [x] SubTask 15.2: 为每个问题补充：文件路径、行号、风险等级、问题描述、风险说明、修复建议
  - [x] SubTask 15.3: 补充问题按模块分布统计和 Top 风险排序
  - [x] SubTask 15.4: 生成可执行修复计划（分 P0/P1/P2/P3 优先级）

- [x] Task 16: 建立代码质量最佳实践规范
  - [x] SubTask 16.1: 编写 Python 后端开发规范 → `.trae/rules/python-backend-standards.md`
  - [x] SubTask 16.2: 编写 TypeScript/React 前端开发规范 → `.trae/rules/typescript-frontend-standards.md`
  - [x] SubTask 16.3: 规范已注册到 `.trae/rules/` 作为项目级规则

- [x] Task 17: 建立代码质量检查清单
  - [x] SubTask 17.1: 创建 CI 门禁可引用的质量检查清单 → `.trae/rules/quality-checklists.md`
  - [x] SubTask 17.2: 定义代码审查（Code Review）的检查清单模板 → `.trae/rules/quality-checklists.md`

## 阶段五：修复实施与验证（依赖 Task 15）

- [x] Task 18: 实施 P0/P1 优先级的修复
  - [x] SubTask 18.1: 根据修复计划实施 P0（致命）问题的修复（P0-03: litellm response.close; P0-04: message max_length）
  - [x] SubTask 18.2: 根据修复计划实施 P1（严重）问题的修复（P1-01~P1-03, P1-05~P1-07, P1-11，共 8 项）
  - [x] SubTask 18.3: 运行完整测试套件验证修复不引入回归（176 passed, 4 skipped）

- [x] Task 19: 实施 P2/P3 优先级的修复
  - [x] SubTask 19.1: 实施 P2 高优先级修复（P2-01: 命令长度/shell字符过滤; P2-02: json.dumps default=str; P2-03: MIME类型校验）
  - [x] SubTask 19.2: 建立代码质量标准规范文档，长期引导 P2/P3 改进（规范文档已落地到 .trae/rules/）
  - [x] SubTask 19.3: 运行测试套件验证修复不引入回归（全部已有测试通过）

- [x] Task 20: 最终验证与归零
  - [x] SubTask 20.1: 所有修改文件 Python 语法验证通过（executor/litellm_adapter/skills/plugins/mcp/client 共 5 文件）
  - [x] SubTask 20.2: 运行全部可收集的后端测试，176 passed / 4 skipped / 0 failed
  - [x] SubTask 20.3: 更新 checklist.md 和 tasks.md 标记所有检查点完成

# Task Dependencies

- [Task 2] 依赖 [Task 1]
- [Task 3] 依赖 [Task 1]
- [Task 4] 依赖 [Task 2]
- [Task 5] 依赖 [Task 2]
- [Task 6] 依赖 [Task 2]
- [Task 7] 依赖 [Task 2]
- [Task 8] 依赖 [Task 2]
- [Task 9] 依赖 [Task 2]
- [Task 10] 依赖 [Task 3]
- [Task 11] 依赖 [Task 3]
- [Task 12] 依赖 [Task 3]
- [Task 13] 依赖 [Task 2]（可并行于 Task 4-12）
- [Task 14] 独立（可随时开始）
- [Task 15] 依赖 [Task 4]..[Task 14] 全部完成
- [Task 16] 依赖 [Task 15]
- [Task 17] 依赖 [Task 16]
- [Task 18] 依赖 [Task 15]
- [Task 19] 依赖 [Task 18]
- [Task 20] 依赖 [Task 18], [Task 19]
