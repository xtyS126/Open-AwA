# 第二章：API 参考

## 2.1 核心 API

### BasePlugin

所有插件的基类，位于 `backend/plugins/base_plugin.py`。

```python
from backend.plugins.base_plugin import BasePlugin
```

#### 类属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | `""` | 插件唯一标识符 |
| `version` | str | `"1.0.0"` | 插件版本号（SemVer） |
| `description` | str | `""` | 插件功能描述 |

#### 构造函数

```python
BasePlugin(config: Optional[Dict[str, Any]] = None)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `dict` \| None | 插件配置字典，可从 manifest.json 传入 |

#### 抽象方法

**`initialize() -> bool`**

插件初始化方法，在首次加载时调用。返回 `True` 表示初始化成功，`False` 表示失败（插件将进入 error 状态）。

```python
def initialize(self) -> bool:
    self._initialized = True
    return True
```

**`execute(*args, **kwargs) -> Any`**

插件主执行逻辑，当系统调用该插件时触发。

```python
def execute(self, *args, **kwargs) -> Any:
    return {"result": "ok"}
```

#### 可重写方法

**`cleanup() -> None`**

插件卸载前的清理逻辑，默认将 `_initialized` 设为 False。

**`validate() -> bool`**

插件注册前的配置校验，默认返回 `True`。建议重写以检查必要的配置项。

**`rollback(previous_state: str, context: Optional[Dict[str, Any]] = None) -> bool`**

热更新失败时的回滚逻辑，默认将状态恢复到 `previous_state`。

#### 实例属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `config` | `Dict[str, Any]` | 构造时传入的配置字典 |
| `_initialized` | bool | 是否已完成初始化 |
| `_state` | str | 当前状态字符串 |

---

### PluginStateMachine

管理插件的状态流转，位于 `backend/plugins/plugin_lifecycle.py`。

#### 合法状态转换

```
registered  --> loaded, error
loaded      --> enabled, unloaded, error
enabled     --> disabled, updating, error
disabled    --> enabled, unloaded, error
updating    --> loaded, error
error       --> unloaded, loaded
unloaded    --> loaded
```

#### 方法

**`get_state(plugin_name: str) -> PluginState`**

获取指定插件的当前状态。

**`can_transition(plugin_name: str, to_state: PluginState) -> bool`**

检查插件是否可以转换到目标状态。

---

## 2.2 扩展点 API

### ExtensionPointType

枚举类，定义所有支持的扩展点类型，位于 `backend/plugins/extension_protocol.py`。

| 枚举值 | 字符串值 | 用途 |
|--------|----------|------|
| `TOOL` | `"tool"` | 向 AI 智能体注册可调用工具 |
| `HOOK` | `"hook"` | 在系统流程中插入前置/后置逻辑 |
| `COMMAND` | `"command"` | 注册用户可触发的命令 |
| `ROUTE` | `"route"` | 注册自定义 HTTP 路由 |
| `EVENT_HANDLER` | `"event_handler"` | 订阅并处理系统事件 |
| `SCHEDULER` | `"scheduler"` | 注册定时任务 |
| `MIDDLEWARE` | `"middleware"` | 注册 HTTP 中间件 |
| `DATA_PROVIDER` | `"data_provider"` | 注册数据提供者 |

### ExtensionRegistry

管理所有插件的扩展点注册，通常由 `PluginManager` 内部使用。

#### 注册方法

```python
registry.register_tool(plugin_name, name, version, config)
registry.register_hook(plugin_name, name, version, config)
registry.register_command(plugin_name, name, version, config)
registry.register_route(plugin_name, name, version, config)
registry.register_event_handler(plugin_name, name, version, config)
registry.register_scheduler(plugin_name, name, version, config)
registry.register_middleware(plugin_name, name, version, config)
registry.register_data_provider(plugin_name, name, version, config)
```

所有方法均返回 `ExtensionRegistration` 对象。

**`register_manifest(plugin_name: str, manifest: Dict[str, Any]) -> List[ExtensionRegistration]`**

批量注册 manifest.json 中声明的所有扩展点。

**`get_extensions(point: ExtensionPointType) -> List[ExtensionRegistration]`**

获取指定扩展点类型的所有注册信息。

### manifest.json 扩展点声明格式

```json
{
  "extensions": [
    {
      "point": "tool",
      "name": "my_tool_name",
      "version": "1.0.0",
      "config": {
        "description": "工具描述",
        "parameters": {}
      }
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `point` | string | 是 | 扩展点类型，取值见上表 |
| `name` | string | 是 | 扩展点名称，在同一插件内唯一 |
| `version` | string | 是 | SemVer 格式版本号 |
| `config` | object | 否 | 扩展点附加配置 |

---

## 2.3 存储 API

插件可以通过 `config` 字典持久化配置数据。对于运行时状态存储，推荐使用以下模式：

### 插件配置存储

在 manifest.json 中声明的配置项会通过构造函数传入：

```python
class MyPlugin(BasePlugin):
    def __init__(self, config=None):
        super().__init__(config)
        # 读取配置
        self.theme = self.config.get("theme", "light")
        self.max_items = self.config.get("max_items", 100)
```

### REST API 存储接口

通过后端 HTTP 接口进行数据持久化：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/plugins/{name}/config` | GET | 获取插件配置 |
| `/api/plugins/{name}/config` | PUT | 更新插件配置 |
| `/api/plugins/{name}/state` | GET | 获取插件当前状态 |

---

## 2.4 事件 API

### 支持的扩展点事件类型

使用 `event_handler` 扩展点订阅系统事件：

```json
{
  "point": "event_handler",
  "name": "on_chat_message",
  "version": "1.0.0",
  "config": {
    "event": "chat.message.received"
  }
}
```

### 在插件中处理事件

```python
class MyEventPlugin(BasePlugin):
    name = "my-event-plugin"
    version = "1.0.0"
    description = "事件处理示例插件"

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Any:
        event_type = kwargs.get("event_type", "")
        event_data = kwargs.get("event_data", {})

        if event_type == "chat.message.received":
            return self._handle_chat_message(event_data)
        return {"status": "ignored"}

    def _handle_chat_message(self, data: dict) -> dict:
        message = data.get("message", "")
        return {"processed": True, "message_length": len(message)}
```

### 系统内置事件列表

| 事件名称 | 触发时机 | 数据结构 |
|----------|----------|----------|
| `plugin.loaded` | 插件加载完成 | `{plugin_name, version}` |
| `plugin.enabled` | 插件启用 | `{plugin_name}` |
| `plugin.disabled` | 插件禁用 | `{plugin_name}` |
| `plugin.error` | 插件发生错误 | `{plugin_name, error}` |
| `chat.message.received` | 收到聊天消息 | `{session_id, message, role}` |

---

## 2.5 权限 API

### 权限声明

在 manifest.json 的 `permissions` 字段中声明所需权限：

```json
{
  "permissions": [
    "file:read",
    "network:http"
  ]
}
```

### 内置权限类型

| 权限标识 | 允许的操作 |
|----------|------------|
| `file:read` | 使用 `open()` 读取文件 |
| `file:write` | 使用 `open()`、`remove()`、`unlink()`、`rmtree()` 写入/删除文件 |
| `network:http` | 使用 `requests`、`httpx`、`urllib` 等发起 HTTP 请求 |

### 权限校验机制

`PluginManager` 在加载插件时会通过静态代码分析（AST 扫描）检测插件代码中的 API 使用是否与 manifest.json 中声明的权限一致：

- 若插件使用了未声明的危险 API，加载将被拒绝
- 以下 API 无论是否声明权限都被无条件禁止：`eval`、`exec`、`compile`、`subprocess`、`ctypes`、`pickle`、`marshal`

### 沙箱限制

`PluginSandbox` 为所有插件的执行提供运行时保护：

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 执行超时 | 30 秒 | 单次 execute 调用的最长执行时间 |
| 内存限制 | 512m | 插件可使用的最大内存 |
| CPU 限制 | 1.0 | CPU 配额（1.0 = 100% 单核） |

### 权限校验示例

```python
class NetworkPlugin(BasePlugin):
    name = "network-plugin"
    version = "1.0.0"
    description = "需要网络权限的插件"

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Any:
        import httpx
        url = kwargs.get("url", "")
        response = httpx.get(url)
        return {"status_code": response.status_code}
```

对应的 manifest.json 必须声明：

```json
{
  "permissions": ["network:http"]
}
```
