# Checklist

- [x] SubagentExecutionContainer 不再使用 `ansi-to-html` 的 `Convert`
- [x] SubagentExecutionContainer 使用 `MessageContent` 渲染子代理输出
- [x] 子代理名称在输出区域顶部正确显示
- [x] 子代理状态文字/指示灯正确显示（运行中/已完成/异常）
- [x] 日志截断提示在 `truncated=true` 时正确显示
- [x] 子代理输出的 Markdown 内容正确渲染（标题、列表、代码块、表格、数学公式）
- [x] 纯文本输出保留换行且无异常样式
- [x] SubagentExecutionContainer 样式不再是深色终端风格，与主聊天气泡一致
- [x] AssistantThoughtSegment 中子代理区域布局正常
- [x] `ansi-to-html` 依赖已确认是否需要移除
- [x] 单元测试更新并通过
- [x] TypeScript 类型检查零错误
- [x] ESLint 零错误
