# 第二章：API 参考

本章只覆盖当前仓库中能够直接定位到的插件核心 API 与相关接口，不额外补充未在代码中出现的虚拟能力。

## 1. BasePlugin

所有插件基类位于：

- [base_plugin.py](file:///d:/代码/Open-AwA/backend/plugins/base_plugin.py#L5-L58)

### 1.1 类属性

| 属性 | 说明 |
| --- | --- |
| `name` | 插件名称 |
| `version` | 插件版本 |
| `description` | 插件描述 |
| `enable_count` | 类属性，默认 `0` |
| `rollback_events` | 回滚事件记录列表 |

### 1.2 构造函数

```python
BasePlugin(config: Optional[Dict[str, Any]] = None)
```

实例初始化后，基类会创建：

- `self.config`
- `self._initialized`
- `self._state`

### 1.3 必须实现的方法

```python
def initialize(self) -> bool: ...
def execute(self, *args, **kwargs) -> Any: ...
```

### 1.4 可重写的方法

```python
def cleanup(self) -> None: ...
def validate(self) -> bool: ...
def rollback(self, previous_state: str, context: Optional[Dict[str, Any]] = None) -> bool: ...
```

### 1.5 生命周期钩子

```python
def on_registered(self) -> None: ...
def on_loaded(self) -> None: ...
def on_enabled(self) -> None: ...
def on_disabled(self) -> None: ...
def on_unloaded(self) -> None: ...
def on_updating(self) -> None: ...
def on_error_state(self) -> None: ...
def on_error(self, error: Exception, from_state: str, to_state: str) -> None: ...
```

## 2. 扩展点注册

扩展点定义位于：

- [extension_protocol.py](file:///d:/代码/Open-AwA/backend/plugins/extension_protocol.py#L8-L156)

### 2.1 支持的扩展点类型

| 类型 | 字符串值 |
| --- | --- |
| TOOL | `tool` |
| HOOK | `hook` |
| COMMAND | `command` |
| ROUTE | `route` |
| EVENT_HANDLER | `event_handler` |
| SCHEDULER | `scheduler` |
| MIDDLEWARE | `middleware` |
| DATA_PROVIDER | `data_provider` |

### 2.2 ExtensionRegistration

扩展点注册对象包含：

- `plugin_name`
- `point`
- `name`
- `version`
- `config`

### 2.3 ExtensionRegistry 常用方法

```python
register_extension(plugin_name, extension)
register_manifest(plugin_name, manifest)
unregister_plugin(plugin_name)
list_by_point(point)
list_plugin_extensions(plugin_name)
get_registry_snapshot()
```

也提供按扩展点类型拆分的快捷方法：

```python
register_tool(...)
register_hook(...)
register_command(...)
register_route(...)
register_event_handler(...)
register_scheduler(...)
register_middleware(...)
register_data_provider(...)
```

## 3. 动态加载与实例化

相关实现：

- [plugin_loader.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_loader.py#L11-L93)

### 3.1 PluginLoader

当前 `PluginLoader` 主要负责：

- 从文件路径加载模块
- 找出继承 `BasePlugin` 的类
- 缓存已加载插件类
- 根据配置实例化插件
- 注入配置
- 查询加载状态

### 3.2 关键方法

```python
load_module(plugin_path: str) -> Optional[Type[BasePlugin]]
instantiate_plugin(plugin_class: Type[BasePlugin], config: Dict) -> Optional[BasePlugin]
inject_config(plugin_instance: BasePlugin, config: Dict) -> None
get_loading_state(plugin_name: str) -> str
```

## 4. 插件校验

相关实现：

- [plugin_validator.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_validator.py#L24-L160)

### 4.1 校验内容

当前 `PluginValidator` 会检查：

- 插件类是否继承 `BasePlugin`
- 是否具备 `initialize`、`execute`、`cleanup`
- 配置是否包含 `name`、`version`
- `dependencies` 是否为字符串列表
- 插件实例的 `validate()` 是否返回 `True`

### 4.2 返回值

`validate_plugin()` 返回 `ValidationResult`，包含：

- `valid`
- `errors`
- `warnings`

## 5. 插件沙箱

相关实现：

- [plugin_sandbox.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_sandbox.py#L8-L121)

### 5.1 作用

当前 `PluginSandbox` 实现了执行包装能力，重点是：

- 支持同步与异步插件方法
- 异步执行支持超时控制
- 记录执行计数与统计信息

### 5.2 构造参数

```python
PluginSandbox(timeout: int = 30, memory_limit: str = "512m", cpu_limit: float = 1.0)
```

### 5.3 关键方法

```python
async execute_plugin(plugin_instance, method, **kwargs)
execute_plugin_sync(plugin_instance, method, **kwargs)
get_execution_stats()
reset_stats()
```

说明：

- 当前代码中 `memory_limit` 和 `cpu_limit` 主要体现在配置与统计输出上
- 真正的操作系统级资源限制并未在该文件中直接实现

## 6. 生命周期状态机

相关实现：

- [plugin_lifecycle.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_lifecycle.py#L13-L220)

### 6.1 状态枚举

| 状态 | 值 |
| --- | --- |
| REGISTERED | `registered` |
| LOADED | `loaded` |
| ENABLED | `enabled` |
| DISABLED | `disabled` |
| UNLOADED | `unloaded` |
| ERROR | `error` |
| UPDATING | `updating` |

### 6.2 合法状态流转

```text
registered -> loaded, error
loaded -> enabled, unloaded, error
enabled -> disabled, updating, error
disabled -> enabled, unloaded, error
updating -> loaded, error
error -> unloaded, loaded
unloaded -> loaded
```

### 6.3 关键对象

- `PluginStateMachine`：保存和查询状态
- `TransitionExecutor`：执行状态迁移、回滚、错误钩子、幂等缓存

## 7. 插件管理 API

后端插件路由位于：

- [plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L15-L519)

### 7.1 基础管理接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/plugins` | 获取插件列表 |
| GET | `/api/plugins/{plugin_id}` | 获取单个插件 |
| POST | `/api/plugins` | 在数据库中创建插件记录 |
| PUT | `/api/plugins/{plugin_id}` | 更新插件记录 |
| DELETE | `/api/plugins/{plugin_id}` | 删除插件记录 |
| PUT | `/api/plugins/{plugin_id}/toggle` | 启用或禁用 |

### 7.2 执行与工具接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/plugins/{plugin_id}/execute` | 执行插件方法 |
| GET | `/api/plugins/{plugin_id}/tools` | 获取插件暴露的工具描述 |

### 7.3 权限与日志接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/plugins/{plugin_id}/permissions` | 查询插件权限状态 |
| POST | `/api/plugins/{plugin_id}/permissions/authorize` | 授权权限 |
| POST | `/api/plugins/{plugin_id}/permissions/revoke` | 撤销权限 |
| GET | `/api/plugins/{plugin_id}/logs` | 读取插件日志 |

### 7.4 上传、发现与维护接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/plugins/upload` | 上传并解压 zip 插件包 |
| POST | `/api/plugins/validate` | 校验配置内容 |
| GET | `/api/plugins/discover` | 重新发现插件 |
| POST | `/api/plugins/{plugin_id}/hot-update` | 热更新 |
| POST | `/api/plugins/{plugin_id}/rollback` | 回滚 |

## 8. 前端插件 API 封装

前端请求封装见：

- [api.ts](file:///d:/代码/Open-AwA/frontend/src/services/api.ts#L110-L134)

当前前端已封装的插件接口包括：

```ts
pluginsAPI.getAll()
pluginsAPI.getOne(id)
pluginsAPI.install(plugin)
pluginsAPI.uninstall(id)
pluginsAPI.toggle(id)
pluginsAPI.upload(file)
pluginsAPI.getPermissions(id)
pluginsAPI.authorizePermissions(id, permissions)
pluginsAPI.revokePermissions(id, permissions)
pluginsAPI.getLogs(id, level?, limit?, offset?)
pluginsAPI.setLogLevel(id, level)
```

## 9. CLI API

插件 CLI 位于：

- [plugin_cli.py](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L11-L166)

当前可用命令：

```powershell
python -m plugins.cli.plugin_cli init ...
python -m plugins.cli.plugin_cli build ...
python -m plugins.cli.plugin_cli validate ...
python -m plugins.cli.plugin_cli sign ...
```

## 10. 测试参考

CLI 测试样例可参考：

- [test_plugin_cli.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_cli.py#L12-L202)

该测试文件验证了：

- 脚手架生成结果
- 打包 zip 文件命名与内容
- zip 包校验
- 签名结果正确性
