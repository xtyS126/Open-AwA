# Open-AwA 插件开发手册

本手册面向 Open-AwA 插件开发者，内容基于当前仓库的插件核心实现、CLI、示例插件和插件管理接口整理，不包含仓库中尚未落地的外部发布平台或插件市场流程。

## 手册结构

- [1. 快速开始](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/1-getting-started.md)
- [2. API 参考](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/2-api-reference.md)
- [3. 最佳实践](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/3-best-practices.md)
- [4. 常见问题](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/4-faq.md)

## 当前插件系统包含的真实能力

根据当前代码，插件系统已经具备以下组成部分：

- `BasePlugin` 插件基类
- `ExtensionRegistry` 扩展点注册中心
- `PluginLoader` 动态加载器
- `PluginValidator` 配置与类校验器
- `PluginSandbox` 超时与执行隔离封装
- `PluginStateMachine` 与 `TransitionExecutor` 生命周期状态管理
- `plugin_cli.py` 插件脚手架、打包、校验、签名命令
- 插件管理 API，包括权限、日志、执行、热更新、回滚等接口

参考代码：

- [base_plugin.py](file:///d:/代码/Open-AwA/backend/plugins/base_plugin.py#L1-L58)
- [extension_protocol.py](file:///d:/代码/Open-AwA/backend/plugins/extension_protocol.py#L8-L156)
- [plugin_loader.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_loader.py#L11-L93)
- [plugin_validator.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_validator.py#L24-L160)
- [plugin_sandbox.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_sandbox.py#L8-L121)
- [plugin_lifecycle.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_lifecycle.py#L13-L220)
- [plugin_cli.py](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L11-L166)
- [plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L15-L519)

## 示例插件

仓库根目录 `plugins/` 下当前可见的示例插件：

- `hello-world`：演示最基础的插件组织方式
- `theme-switcher`：演示主题切换、工具描述与 UI 相关数据输出
- `data-chart`：演示图表数据、请求拦截与模拟数据模式

可参考：

- [manifest.json](file:///d:/代码/Open-AwA/plugins/hello-world/manifest.json)
- [index.py](file:///d:/代码/Open-AwA/plugins/hello-world/src/index.py)
- [index.py](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L28-L145)
- [index.py](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L9-L205)

## 推荐阅读顺序

如果你是第一次接触该仓库的插件体系，建议按以下顺序阅读：

1. 先看 [1-getting-started.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/1-getting-started.md)，了解目录结构、CLI 与基本流程
2. 再看 [2-api-reference.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/2-api-reference.md)，理解基类、扩展点、沙箱和生命周期
3. 然后看 [3-best-practices.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/3-best-practices.md)，减少后续返工
4. 遇到问题时查阅 [4-faq.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/4-faq.md)

## 与当前实现相关的注意事项

- CLI `init` 命令会生成 `manifest.json`、`src/index.py`、`README.md`、`LICENSE`
- CLI `validate` 当前校验对象是插件 zip 包，而不是源码目录
- 后端插件 API 中已实现 `/execute`、`/tools`、`/permissions`、`/logs`、`/hot-update`、`/rollback`
- 插件管理页面支持导入 zip、切换启用状态、查看权限和调试日志

前端相关代码：

- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L1-L260)
- [api.ts](file:///d:/代码/Open-AwA/frontend/src/services/api.ts#L110-L134)
