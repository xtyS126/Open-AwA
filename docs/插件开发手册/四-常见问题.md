# 第四章：常见问题

## Q1：CLI 初始化后为什么 `src/index.py` 里只有一个 `run()` 占位函数？

这是当前脚手架的实现结果。CLI `init` 只是帮你生成最小文件集，不会自动生成继承 `BasePlugin` 的完整类。

相关代码：

- [cmd_init](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L16-L55)

实际开发时，需要你手工把它改造成继承 `BasePlugin` 的类实现。

## Q2：`validate` 命令为什么不能直接校验插件目录？

因为当前 CLI 的 `validate` 命令接收参数名就是 `zip_path`，内部逻辑也是按 zip 文件读取的。

参考：

- [cmd_validate](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L97-L140)

推荐流程是先 `build`，再 `validate`。

## Q3：插件最少要实现哪些方法？

至少要实现：

- `initialize()`
- `execute()`

并继承 `BasePlugin`。

参考：

- [BasePlugin](file:///d:/代码/Open-AwA/backend/plugins/base_plugin.py#L5-L58)

## Q4：当前支持哪些扩展点？

当前代码中支持 8 类扩展点：

- `tool`
- `hook`
- `command`
- `route`
- `event_handler`
- `scheduler`
- `middleware`
- `data_provider`

参考：

- [ExtensionPointType](file:///d:/代码/Open-AwA/backend/plugins/extension_protocol.py#L8-L16)

## Q5：插件执行超时怎么处理？

当前 `PluginSandbox` 默认超时 30 秒。先优先优化插件执行路径，而不是直接放大超时值。

参考：

- [PluginSandbox](file:///d:/代码/Open-AwA/backend/plugins/plugin_sandbox.py#L8-L17)

建议：

1. 外部请求设置超时
2. 控制一次处理的数据量
3. 将 IO 操作异步化
4. 使用缓存减少重复计算

## Q6：插件 zip 包里为什么要求 `README.md`、`LICENSE` 和 `dist/`？

因为当前 CLI `validate` 会显式检查这些内容是否存在。

参考：

- [cmd_validate](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L109-L140)

## Q7：如何查看插件日志？

后端提供日志读取接口，前端插件页也提供调试面板入口。

参考：

- [get_plugin_logs](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L500-L519)
- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L213-L241)

## Q8：上传 zip 后，插件为什么没有立即变成“完整可用”的业务能力？

当前 `/api/plugins/upload` 的逻辑主要负责：

- 解压 zip
- 重新发现插件
- 如数据库里不存在同名插件，则创建基础记录

参考：

- [upload_plugin](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L371-L421)

它不是一个完整的“插件商店安装器”，因此如果插件本身结构或代码不完整，上传成功也不代表业务逻辑一定能执行成功。

## Q9：怎样确认插件是否真的被动态加载？

可以从几个角度验证：

1. 调用 `/api/plugins/discover`
2. 调用 `/api/plugins/{plugin_id}/tools`
3. 调用 `/api/plugins/{plugin_id}/execute`
4. 查看插件日志

相关代码：

- [discover_plugins](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L351-L369)
- [get_plugin_tools](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L248-L278)
- [execute_plugin](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L203-L245)

## Q10：插件权限是怎么管理的？

当前后端已提供：

- 查询权限状态
- 授权权限
- 撤销权限

参考：

- [get_plugin_permissions](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L179-L200)
- [authorize_plugin_permissions](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L127-L151)
- [revoke_plugin_permissions](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L153-L176)

前端权限弹窗见：

- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L55-L98)

## Q11：是否可以假设存在完整的插件市场、发布中心或审核平台？

不建议。当前仓库中可以看到前端有“浏览插件市场”按钮，但没有发现与之对应的完整市场实现。因此编写插件文档或对外说明时，不应把这部分写成已完成功能。

## Q12：如何给插件写测试？

最直接的方式是：

1. 直接实例化插件类
2. 传入配置
3. 调用 `initialize()`
4. 调用 `execute()`
5. 对返回值断言

也可以参考仓库已有的 CLI 测试风格：

- [test_plugin_cli.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_cli.py#L12-L202)
