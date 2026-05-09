# Tasks

- [x] Task 1: 为 BasePlugin 添加 context 属性和 set_context() 方法
  - 在 `base_plugin.py` 的 `__init__` 中添加 `self.context: Optional[PluginContext] = None`
  - 添加 `set_context(self, context: PluginContext) -> None` 方法
  - 方法内将 `self.context` 赋值为传入的 context
- [x] Task 2: 为 PluginManager 添加 db_session_factory 注入能力
  - 修改 PluginManager.__init__ 接受可选的 `db_session_factory` 参数
  - 在 `_load_action` 中，实例化插件后、initialize() 前，调用 `build_plugin_context()` 构造 PluginContext
  - 调用 `plugin_instance.set_context(context)` 注入上下文
- [x] Task 3: 更新 schema.json 和 config.json 配置定义
  - schema.json：删除 `ai_api_key`/`ai_base_url`/`ai_model` 字段，添加 `ai_model_config_id` 字段（type: integer, x-component: "model-selector", 描述："选择平台已配置的 AI 模型"）
  - config.json：用 `ai_model_config_id: null` 替代旧的 3 个 AI 字段
- [x] Task 4: 重构 TwitterMonitorPlugin 使用 PricingManager 解析模型配置
  - 在 `_refresh_config()` 中解析 `ai_model_config_id`（integer，可为空）
  - 修改 `_call_external_ai_for_summary()`：当 `ai_model_config_id` 存在时，通过 `self.context.get_db_session()` 创建会话，实例化 PricingManager，查询配置并提取 api_key/api_endpoint/model；当不存在时返回提示信息
  - 修改 trigger_auto_fetch() 和 auto_fetch_loop 中的 AI 总结调用，使用新方式获取凭据
  - 添加 session 的 proper cleanup（try/finally）
- [x] Task 5: 前端 PluginConfigPage 添加 model-selector 下拉组件
  - 在 `PluginConfigPage.tsx` 的 `resolveFieldComponent()` 和 `renderFieldControl()` 中处理 `x-component: "model-selector"`
  - 实现 useEffect 从 `/api/billing/configurations` 获取活跃模型列表
  - 渲染为 `<select>` 下拉框，选项显示 `display_name (provider/model)`，值为 config_id
  - 添加一个空选项"请选择 AI 模型"
  - 在 `PluginConfigPage.module.css` 中添加 model-selector 相关样式
- [x] Task 6: 语法验证
  - 对后端所有修改文件运行 `py_compile` 验证 Python 语法
  - 验证前端代码无 TypeScript 编译错误

# Task Dependencies

- Task 2 依赖 Task 1（PluginManager 需要 BasePlugin 有 context 支持）
- Task 4 依赖 Task 2（插件需要 PluginContext 才能访问数据库）
- Task 5 可独立于 Task 4 并行开发（前端 UI 改动不依赖后端数据库解析逻辑）
- 其他 Task 可并行
