# Learnings Log

## Format
See skill self-improvement for entry format.

---

## [LRN-20260419-001] category

**Logged**: 2026-04-19T00:00:00Z
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
executor.py 的 execute_step 是统一的步骤执行入口，所有 action 类型都需要在此路由。

### Details
项目架构中，agent 解析用户输入后生成 steps 列表，其中每个 step 包含 `action` 字段标识操作类型。execute_step 方法根据 action 分发到对应的 `_execute_*` 方法。

**常见 action 类型**:
- `read_files` - 读取文件
- `execute_command` - 执行命令
- `llm_generate/llm_query/llm_explain/llm_chat` - LLM 调用
- `plugin` - 插件执行（本次新增）
- `mcp_tool_call` - MCP 工具调用

**如果缺少某 action 的路由分支，AI 模型输出的该类型 action 将返回 "Unknown action" 错误。**

### Suggested Action
添加新 action 类型时需要同时：
1. 在 execute_step 中添加 `elif action == "xxx":` 分支
2. 实现对应的 `_execute_xxx` 方法
3. 导入必要的依赖模块

### Metadata
- Source: error
- Related Files: backend/core/executor.py
- See Also: ERR-20260419-001
- Pattern-Key: executor.action_routing
- Recurrence-Count: 1
- First-Seen: 2026-04-19
- Last-Seen: 2026-04-19

---

## [LRN-20260419-002] best_practice

**Logged**: 2026-04-19T14:30:00+08:00
**Priority**: high
**Status**: pending
**Area**: frontend, backend

### Summary
修复 "api request failed" 错误时，应同时增强前后端错误日志输出。

### Details
前端 axios 拦截器记录错误时，`console.error` 输出的 JSON 日志被终端简化显示为 `[前端错误] api request failed`，导致调试困难。

修复方法：
1. **前端增强**：在 api.ts 错误拦截器中添加结构化的 `console.error` 输出，包含 HTTP方法、URL、状态码、错误详情、Request-ID
2. **后端增强**：为关键接口添加 try-catch 包装，日志记录具体错误信息

### Suggested Action
遇到 API 请求失败时：
1. 先增强前端错误日志，输出更详细的调试信息
2. 确认后端日志中有无具体异常堆栈
3. 根据具体错误信息定位根因（数据库/配置/依赖等）

### Metadata
- Source: conversation
- Related Files: frontend/src/shared/api/api.ts, backend/api/routes/skills.py
- Pattern-Key: frontend.api_error_logging
- Recurrence-Count: 1
- First-Seen: 2026-04-19
- Last-Seen: 2026-04-19

---
