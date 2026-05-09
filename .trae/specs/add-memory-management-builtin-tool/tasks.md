# Tasks

- [x] Task 1: 创建 MemoryTools 类
  - 在 `backend/core/builtin_tools/memory_tools.py` 新增文件
  - 实现 `MemoryTools` 类，接收 `MemoryManager` 实例
  - 实现 5 个方法：`remember()`、`recall()`、`forget()`、`list_memories()`、`stats()`
  - 每个方法返回 `{"success": true/false, ...}` 格式的字典
  - 参数校验：必填参数缺失时返回 `success: false`

- [x] Task 2: 在 builtin_tool_manager 中注册 memory_* 工具
  - 在 `BUILTIN_TOOL_DEFINITIONS` 中添加 5 个工具的 OpenAI function calling 定义（name + description + parameters schema）
  - 在 `BUILTIN_TOOL_ACTION_MAP` 中添加 5 个工具到 `MemoryTools` 的映射
  - 初始化 `MemoryTools` 实例并在 `execute_tool()` 和 `list_tools()` 中使用

- [x] Task 3: 确认 executor.py 分发兼容
  - 确认 `executor.py` 的 `builtin_` 前缀分发已正确传递给 `builtin_tool_manager.execute_tool()`
  - 确认 `memory_*` 工具定义带 `builtin_` 前缀，executor 剥离后传递给 execute_tool，通过 ACTION_MAP 解析

- [x] Task 4: 编写单元测试
  - 在 `backend/tests/` 下新增 `test_memory_tools.py`
  - 覆盖 5 个工具的正常场景和异常场景（缺参数、记忆不存在等）
  - Mock `MemoryManager` 避免依赖真实数据库

- [x] Task 5: 运行全量测试验证
  - 运行 `pytest` 确认新增测试通过且无回归

# Task Dependencies

- Task 2 依赖 Task 1（需要先实现 MemoryTools 类再注册映射）
- Task 3 可与 Task 1、2 并行（仅确认现有分发逻辑）
- Task 4 依赖 Task 1（需要现有 MemoryTools 才能写测试）
- Task 5 依赖 Task 1-4 全部完成
