# 第三章：最佳实践

本章聚焦当前仓库下插件开发的实际建议，优先覆盖能和现有实现直接对应的内容。

## 1. 先从示例插件抽取模式

在正式编写自己的插件前，建议先对照现有示例：

- [theme-switcher](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L28-L145)
- [data-chart](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L9-L205)

这两个示例已经体现出几个较稳定的写法：

- 在 `__init__` 中只做轻量配置读取
- 在 `initialize()` 中做状态修正和初始化记录
- 在 `execute()` 中通过 `action` 路由不同能力
- 返回统一结构，例如 `status`、`message`、`data`、`tokens`
- 在 `validate()` 中主动检查配置是否合法
- 在 `cleanup()` 中清理缓存和内部状态

## 2. 配置处理建议

### 2.1 `__init__` 中做轻量初始化

推荐做法：

- 读取配置
- 初始化内存变量
- 不做网络请求或重型加载

示例：

```python
class MyPlugin(BasePlugin):
    def __init__(self, config=None):
        super().__init__(config)
        self._api_key = self.config.get("api_key", "")
        self._cache = {}
```

### 2.2 在 `validate()` 中拦截错误配置

当前仓库示例插件都采用了这个模式，例如：

- [theme-switcher validate](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L102-L111)
- [data-chart validate](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L155-L170)

建议校验：

- 必填配置是否存在
- 枚举值是否合法
- 数值范围是否合理
- 外部依赖参数类型是否正确

## 3. 返回值保持稳定

前后端集成场景下，插件返回值越稳定，调用方越容易处理。推荐统一包含：

- `status`
- 与业务相关的主结果字段
- 可选的 `message`

例如：

```python
return {
    "status": "success",
    "data": payload,
    "message": "执行成功"
}
```

避免直接返回裸字符串、混合类型或不带状态位的结构。

## 4. 使用 `action` 组织多能力插件

如果一个插件有多个子功能，当前仓库更接近的写法是在 `execute()` 中读取 `action`，再分发到内部方法。

参考：

- [ThemeSwitcherPlugin.execute](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L49-L61)
- [DataChartPlugin.execute](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L35-L57)

这种写法的优点：

- 对外只暴露一个执行入口
- 便于和插件执行 API 对接
- 更容易和工具描述、权限模型结合

## 5. 日志记录建议

当前仓库使用 Loguru，插件代码中也大量直接使用 `logger`。

建议：

- 关键路径用 `info`
- 参数与分支细节用 `debug`
- 可恢复问题用 `warning`
- 失败信息用 `error`

示例插件可参考：

- [theme-switcher 日志用法](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L39-L46)
- [data-chart 日志用法](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L22-L33)

不要在日志中输出敏感信息原文，例如完整 token、密码、密钥。

## 6. 控制执行时间

`PluginSandbox` 当前默认超时为 30 秒：

- [PluginSandbox](file:///d:/代码/Open-AwA/backend/plugins/plugin_sandbox.py#L8-L17)

因此应尽量避免：

- 长时间阻塞计算
- 无限循环
- 无上限远程请求重试

建议：

- 为外部请求设置 timeout
- 对数据量设置上限
- 对缓存进行清理

`data-chart` 已在远程请求中设置 `timeout=10`，可以作为参考：

- [data-chart _real_fetch](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L81-L101)

## 7. 为工具调用补齐描述

如果插件会被系统当成工具消费，建议实现 `get_tools()` 并提供清晰参数说明。

参考：

- [ThemeSwitcherPlugin.get_tools](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L119-L145)
- [DataChartPlugin.get_tools](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L179-L205)

建议在工具描述中写清楚：

- 工具名称
- 能力说明
- 参数类型
- 必填项
- 枚举范围

## 8. 做好资源清理

如果插件持有缓存、连接或历史记录，应在 `cleanup()` 中释放。

示例：

- [theme-switcher cleanup](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L113-L117)
- [data-chart cleanup](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L172-L177)

## 9. 包结构和打包注意事项

根据 CLI 逻辑，构建 zip 时会重点处理：

- `manifest.json`
- `README.md`
- `LICENSE`
- `dist/`

参考：

- [cmd_build](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L58-L95)
- [cmd_validate](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L97-L140)

建议在交付前确保：

1. `manifest.json` 能被解析
2. `README.md`、`LICENSE` 存在
3. zip 包中存在 `dist/` 目录
4. 执行 `validate` 无错误

## 10. 生命周期与热更新建议

当前仓库已经实现状态机与热更新、回滚接口，因此插件作者应避免把不可恢复状态直接写死在实例中。

建议：

- 初始化逻辑幂等
- `rollback()` 可重复调用
- `on_error()` 中只做错误记录，不做高风险修复动作

生命周期代码：

- [plugin_lifecycle.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_lifecycle.py#L61-L220)

## 11. 测试优先于手工验证

至少为插件补充以下测试：

- 配置校验测试
- 初始化成功与失败测试
- `execute()` 主要路径测试
- 边界参数测试

可先参考现有 CLI 测试风格：

- [test_plugin_cli.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_cli.py#L12-L202)

## 12. 不要依赖未实现的平台能力

编写插件文档或对外说明时，建议只承诺当前仓库中已经落地的能力。比如前端虽然有“浏览插件市场”按钮，但当前仓库并未看到完整市场实现，因此不应把“插件市场”写成既成事实。
