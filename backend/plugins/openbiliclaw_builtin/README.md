# openbiliclaw-builtin

OpenBiliClaw 内置插件，以 vendored 方式将 OpenBiliClaw 完整源码嵌入 Open-AwA，
通过 OpenClaw 适配层对外暴露 10 个技能（账号同步、推荐、对话、推测探针等）。

## 来源与版本

- 上游项目: OpenBiliClaw
- 上游版本: v0.3.147
- 上游仓库: https://github.com/whiteguo233/OpenBiliClaw
- 上游 License: MIT

## 接入方式

- **vendored**：将上游 `src/openbiliclaw/` 完整复制到本目录 `src/openbiliclaw/`，
  不依赖系统已安装的 `openbiliclaw` 包，避免版本漂移。
- 加载入口：`plugin.py` 中的 `OpenBiliClawBuiltinPlugin(BasePlugin)`，
  在 `initialize()` 内通过 `importlib.util.spec_from_file_location` 显式加载
  `src/openbiliclaw/integrations/openclaw/bootstrap.py`，避免污染全局 `sys.path`。
- 适配层：`adapter.py` 中的 `OpenBiliClawAdapter` 包装上游 `OpenClawAdapter`，
  并将 `build_openclaw_skills()` 返回的 `OpenClawSkillDescriptor` 转换为
  Open-AwA 工具定义（`name` / `description` / `parameters` / `handler`）。

## 依赖清单

见 `requirements.txt`。关键依赖：

- `httpx>=0.27`
- `pydantic>=2.0`
- `loguru>=0.7`
- `bilibili-api-python>=16`
- `google-genai>=1.66`
- `ollama>=0.4`
- `openai>=1.0`
- `anthropic>=0.40`

## 如何初始化

1. 安装依赖：`pip install -r backend/plugins/openbiliclaw_builtin/requirements.txt`
2. 启动 Open-AwA 后端，`PluginManager` 会在 `_startup_plugin_load_enabled()`
   中自动 seed 一条 `name="openbiliclaw-builtin"`、`source="builtin"`、
   `category="builtin"`、`enabled=True`、`is_uninstallable=True` 的记录。
3. 加载时若关键依赖缺失，`OpenBiliClawBuiltinPlugin.initialize()` 会抛出
   `BuiltinPluginDependencyError`（携带 `missing_packages` 列表），
   `main.py` 中捕获后仅记录 WARNING，不阻塞启动。
4. 加载成功后通过 `GET /api/plugins` 可见，工具通过 `get_tools()` 暴露给 Agent。

## 卸载说明

该插件 `is_uninstallable=True`，`DELETE /api/plugins/openbiliclaw-builtin` 与
`POST /api/plugins/openbiliclaw-builtin/disable` 端点会返回 403，仅允许"查看配置"。
