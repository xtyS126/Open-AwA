# Checklist

- [x] `memory_remember`：传入有效 `content` 可成功写入长期记忆并返回 `success: true` 和 `memory_id` — [test_memory_tools.py#L41-L51](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L41-L51)
- [x] `memory_remember`：缺少 `content` 时返回 `success: false` 和明确错误信息 — [test_memory_tools.py#L55-L58](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L55-L58)
- [x] `memory_recall`：传入 `query` 可检索到相关记忆并返回列表 — [test_memory_tools.py#L77-L92](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L77-L92)
- [x] `memory_recall`：无匹配时返回 `memories: []` 和提示消息 — [test_memory_tools.py#L96-L106](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L96-L106)
- [x] `memory_forget`：传入有效 `memory_id` 可删除记忆并返回 `success: true` — [test_memory_tools.py#L117-L126](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L117-L126)
- [x] `memory_forget`：记忆不存在时返回 `success: false` 和明确错误信息 — [test_memory_tools.py#L130-L139](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L130-L139)
- [x] `memory_list`：可返回近期记忆摘要列表，包含 id、content(截断)、importance、created_at、archive_status — [test_memory_tools.py#L148-L165](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L148-L165)
- [x] `memory_list`：无记忆时返回空列表和提示消息 — [test_memory_tools.py#L169-L178](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L169-L178)
- [x] `memory_stats`：返回正确的统计信息（total、active、archived、平均置信度、平均质量评分、总访问次数） — [test_memory_tools.py#L182-L200](file:///d:/代码/Open-AwA/backend/tests/test_memory_tools.py#L182-L200)
- [x] `memory_*` 所有工具在 executor 的 `builtin_` 分发分支中可被正确路由 — executor.py [L1169-L1182](file:///d:/代码/Open-AwA/backend/core/executor.py#L1169-L1182) 已验证
- [x] `memory_*` 所有工具定义正确注册到 `builtin_tool_manager`，Agent 可在 tool calling 中看到 — manager.py [BUILTIN_TOOL_DEFINITIONS](file:///d:/代码/Open-AwA/backend/core/builtin_tools/manager.py#L232-L298) + [BUILTIN_TOOL_ACTION_MAP](file:///d:/代码/Open-AwA/backend/core/builtin_tools/manager.py#L33-L37)
- [x] 单元测试覆盖所有 5 个工具的正常和异常场景，全部通过 — 16 passed
- [x] 全量 `pytest` 无回归 — 862 passed, 5 skipped
