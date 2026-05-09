# Checklist

## 阶段一：审查准备
- [x] 项目最新目录结构和源文件清单已确认
- [x] 历史审查报告已回顾，差异已识别
- [x] 静态分析工具配置已就绪
- [x] 当前测试套件通过率已记录（后端 1 fail + 1 collection error，前端 8 fail / 96 pass）

## 阶段二：自动化扫描结果
- [x] pylint 扫描完成，结果已记录
- [x] mypy 类型检查完成，结果已记录（65 个类型错误，跨 23 个文件）
- [x] bandit 安全扫描完成，结果已记录（B104/B105/B106/B108/B110/B307）
- [x] ESLint 扫描完成，结果已记录（需先修复缺失包依赖）
- [x] TypeScript 类型检查完成，结果已记录（0 错误通过）

## 阶段三：后端核心模块审查 — 异常处理与边界条件
- [x] `core/agent.py` 审查完成 — 主循环异常捕获、多轮工具调用错误传播、中断恢复（8 项发现）
- [x] `core/executor.py` 审查完成 — 工具执行异常处理、超时控制、重试逻辑（7 项发现）
- [x] `core/litellm_adapter.py` 审查完成 — LLM 调用异常、流式解析错误、退避策略（6 项发现）
- [x] `core/planner.py`、`core/comprehension.py` 审查完成 — 空输入、异常路径（5 项发现）

## 阶段三：后端 API 层 — 输入验证与数据校验
- [x] `api/routes/chat.py` 审查完成 — 消息输入验证、会话 ID 校验、流式参数校验（2 项发现）
- [x] `api/routes/auth.py`、`api/routes/security.py` 审查完成（2 项发现）
- [x] `api/routes/plugins.py`、`api/routes/skills.py` 审查完成（4 项发现）
- [x] `api/routes/billing/`、`api/routes/weixin.py` 审查完成（5 项发现）
- [x] `api/dependencies.py`、`api/schemas.py` 审查完成（4 项发现）

## 阶段三：日志记录与错误处理充分性
- [x] 关键路径错误传播审查完成（chat、agent、executor）
- [x] 所有 `except` 块合理性审查完成
- [x] 日志上下文完整性审查完成（请求 ID、用户 ID、会话 ID）
- [x] 敏感信息泄露风险审查完成

## 阶段三：并发与内存安全
- [x] 全局变量/模块级状态审查完成
- [x] 插件沙箱资源隔离与释放审查完成
- [x] WebSocket 连接生命周期审查完成
- [x] 数据库会话生命周期审查完成

## 阶段三：代码复用与模块化
- [x] 后端重复代码模式检测完成
- [x] 过度耦合（循环引用、上帝函数、超大类）检测完成
- [x] 未使用资源检测完成

## 阶段三：性能瓶颈
- [x] ORM 查询审查完成（N+1、无索引、无分页）
- [x] LLM 调用链性能审查完成
- [x] 文件 I/O 操作审查完成
- [x] 前端渲染性能审查完成

## 阶段三：前端核心审查
- [x] `features/chat/` 完整审查完成（ChatPage、chatStore、chatCache、流式处理）
- [x] `shared/api/api.ts` 审查完成 — API 异常处理、超时、重试
- [x] `shared/components/ErrorBoundary.tsx` 审查完成
- [x] 表单输入校验审查完成
- [x] API 响应类型与实际数据一致性审查完成
- [x] `any` 类型使用情况审查完成
- [x] Store 状态管理审查完成（chatStore、authStore、themeStore）
- [x] useEffect 依赖数组审查完成
- [x] 事件监听器注册与清理审查完成

## 阶段三：插件系统
- [x] 插件加载链路异常隔离审查完成
- [x] 插件热更新竞态条件审查完成
- [x] 插件-主进程通信安全审查完成
- [x] 5 个活动插件代码质量审查完成

## 阶段三：测试体系
- [x] 后端测试覆盖率评估完成
- [x] 前端测试覆盖率评估完成
- [x] 测试用例有效性评估完成

## 阶段四：审查报告
- [x] 报告已按风险等级分类汇总 → `review_report.md`
- [x] 每条问题包含文件路径、行号、风险等级、描述、风险说明、修复建议
- [x] 问题按模块分布统计和 Top 风险排序已完成
- [x] 可执行修复计划已生成（分4个阶段，含工作量估计和前置依赖）

## 阶段四：最佳实践规范
- [x] Python 后端开发规范已编写 → `.trae/rules/python-backend-standards.md`
- [x] TypeScript/React 前端开发规范已编写 → `.trae/rules/typescript-frontend-standards.md`
- [x] 规范已注册到 `.trae/rules/` 作为项目级规则

## 阶段四：质量检查清单
- [x] CI 门禁质量检查清单已创建 → `.trae/rules/quality-checklists.md`
- [x] Code Review 检查清单模板已创建 → `.trae/rules/quality-checklists.md`

## 阶段五：修复实施
- [x] P0（致命）问题已修复并验证（2 项：P0-03 response.close, P0-04 message max_length）
- [x] P1（严重）问题已修复并验证（8 项：P1-01~P1-03, P1-05~P1-07, P1-11）
- [x] P2（一般）高优先级问题已修复并验证（3 项：P2-01 命令安全, P2-02 json.dumps, P2-03 MIME校验）
- [x] P3（建议）已通过规范文档长期引导改进

## 最终验证
- [x] 所有修改文件 Python 语法验证通过（5 个文件：executor/litellm_adapter/skills/plugins/mcp/client）
- [x] 后端 pytest 176 passed / 4 skipped / 0 failed
- [x] 无引入新的回归问题（litellm_adapter.py 回归已在测试中发现并修复）
