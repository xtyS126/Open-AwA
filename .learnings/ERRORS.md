# Errors Log

## Format
See skill self-improvement for entry format.

---

## [ERR-20260419-001] agent.py plugin 调用缺失 action="plugin" 分支

**Logged**: 2026-04-19T00:00:00Z
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
executor.py 的 execute_step 方法缺少 `action="plugin"` 分支，导致 AI 模型通过标准 action 格式调用插件时失败。

### Error
用户尝试用以下格式调用 twitter-monitor 插件时失败：
```json
{"action": "plugin", "action_input": {"plugin_name": "twitter-monitor", "tool_name": "get_twitter_daily_tweets"}}
```

AI 模型输出该 JSON，但系统返回 `Unknown action: plugin`。

### Context
- executor.py 的 execute_step 只处理内置 action 类型（read_files/execute_command/llm_*/mcp_tool_call）
- 插件调用需要通过 agent.py 的 execute_plugin 方法，但 execute_step 无法路由到此方法
- agent.py 中多处直接调用 execute_plugin，但 agent 解析的 steps 最终通过 executor.execute_step 执行

### Suggested Fix
在 executor.py 中：
1. 添加 `from plugins import plugin_instance` 导入
2. 在 execute_step 的 action 分支中添加 `elif action == "plugin": result = await self._execute_plugin(step, context)`
3. 添加 `_execute_plugin` 方法处理插件执行

### Resolution
- **Resolved**: 2026-04-19
- **Commit**: 通过 SearchReplace 添加了 _execute_plugin 和 action="plugin" 分支
- **Notes**: 现在支持通过标准 action 格式调用插件

### Metadata
- Reproducible: yes
- Related Files: backend/core/executor.py, backend/core/agent.py
- See Also: LRN-20260419-001 (关联的学习条目)

---
