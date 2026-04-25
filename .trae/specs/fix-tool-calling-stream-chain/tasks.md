# Tasks

- [x] Task 1: Backend — agent.py process_stream 支持 tool_calls 闭环
  - [x] 在 `process_stream()` 中添加外层 while 循环（max_rounds=5），从 `_call_llm_api_stream()` 中检测 `type: "tool_calls"` 事件，调用 executor 执行工具，回注 tool_results 后再进入下一轮 LLM 调用
- [x] Task 2: Backend — executor.py 流式/非流式工具执行辅助方法
  - [x] `_execute_tool_call()`: 解析 tool_call 中的 function.name/arguments
  - [x] `_build_tool_message()`: 将工具执行结果格式化为 role:tool 消息
  - [x] `_call_llm_api_stream()` 透传 `type: "tool_calls"` 事件
  - [x] `_call_llm_api()` 非流式路径的 tool_calls 循环（检测 -> 执行 -> 回注 -> 重调 LLM）
- [x] Task 3: Backend — chat_protocol.py 工具事件 helper
  - [x] 新增 `emit_task_event()` 和 `emit_tool_event()`，用于在 SSE 流中发出 task/tool 状态事件
- [x] Task 4: Frontend — 兼容乱序/迟到的 tool 事件（旁置）
  - [x] examiner: `handleSend()` 中已有 `applyTaskUpdate`/`applyToolUpdate` 调用
  - [x] examiner: `applyTaskUpdate` 与 `applyToolUpdate` 在 executionMeta.ts 中已是幂等合并实现
- [x] Task 5: Frontend — 验证 SSE 事件分发路径（旁置）
  - [x] examiner: `handleSend()` 的 SSE 流中已正确区分 `task`/`tool`/`status` 事件
  - [x] examiner: 非数据类 SSE 事件不会干扰消息内容的追加逻辑
- [x] Task 6: 测试与验证
  - [x] `test_litellm_adapter.py`: 33 个测试全部通过
  - [x] `test_executor_tool_calling.py`: 2 个测试全部通过
  - [x] `test_chat_streaming_status.py`: 2 个测试全部通过
  - [x] 检验所有 upstream 测试不受影响（预存在 3 个失败的测试与本次变更无关）

# Task Dependencies
- Task 1, 2, 3 可并行实现
- Task 6 依赖 Task 1-3 完成
- Task 4, 5 可并行评审
