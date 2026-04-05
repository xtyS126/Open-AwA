- **修复配置清理无效的问题**：在 `update_configuration` 接口中，旧代码通过 `if v is not None` 进行过滤更新参数，导致前端显式传递的 `max_tokens: null`（即清空输入框时）被丢弃，无法真正从数据库中清除最大 token 配置。我已将其修正为使用 Pydantic 提供的 `update_data.dict(exclude_unset=True)` 方式，确保只过滤未显式传递的字段，保留显式传递的空值，使之能正常将数据库相应字段设为 `null`。
- **排查并定位显示异常的原因**：前端配置未能显示保存后的 token 数值，根本原因是 **当前正在运行的后端服务可能尚未重启**，没有加载我们稍早前对 `billing.py` 做出的模型字段补充修改。导致：
  1. 保存时：旧版 `ModelConfigUpdateRequest` 模型没有 `max_tokens`，传递的数值被静默丢弃。
  2. 获取时：旧版 `serialize_configuration` 返回的数据也不包含 `max_tokens`。
  
**建议操作**：
请 **手动重启一次你的后端服务**（如重启正在运行的 `python main.py` 或 `uvicorn` 进程）。重启后，前端页面重新获取或保存最大 Token 数的功能即可正常生效。刚才修复清空逻辑的代码也已执行 `git commit`。