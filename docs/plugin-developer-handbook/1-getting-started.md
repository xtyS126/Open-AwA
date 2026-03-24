# 第一章：快速入门

## 1.1 环境准备

### 系统要求

| 依赖项 | 最低版本 | 推荐版本 |
|--------|----------|----------|
| Python | 3.10 | 3.12 |
| Node.js | 18.0 | 20.x LTS |
| Git | 2.30 | 最新稳定版 |

### 克隆仓库

```bash
git clone https://github.com/your-org/Open-AwA.git
cd Open-AwA
```

### 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 安装前端依赖

```bash
cd frontend
npm install
```

### 启动开发服务器

```bash
# 终端1：启动后端
cd backend
uvicorn main:app --reload --port 8000

# 终端2：启动前端
cd frontend
npm run dev
```

## 1.2 创建第一个插件

### 目录结构

每个插件是一个独立目录，位于项目根目录的 `plugins/` 下，结构如下：

```
plugins/
  my-plugin/
    manifest.json      # 插件元数据（必须）
    src/
      index.py         # 插件主入口（必须）
    README.md          # 插件说明文档（推荐）
```

### 编写 manifest.json

`manifest.json` 是插件的身份证，系统通过它识别和加载插件。

```json
{
  "name": "my-first-plugin",
  "version": "1.0.0",
  "pluginApiVersion": "1.0",
  "description": "我的第一个插件",
  "author": "你的名字",
  "permissions": [],
  "extensions": [
    {
      "point": "tool",
      "name": "my_tool",
      "version": "1.0.0",
      "config": {}
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 插件唯一标识符，建议使用小写字母和连字符 |
| version | string | 是 | 遵循 SemVer 规范，如 1.0.0 |
| pluginApiVersion | string | 是 | 当前支持 "1.0" |
| description | string | 否 | 插件功能描述 |
| author | string | 否 | 开发者名称 |
| permissions | string[] | 否 | 所需权限列表，留空表示无特殊权限需求 |
| extensions | array | 是 | 至少包含一个扩展点声明 |

### 编写插件主入口 src/index.py

所有插件必须继承 `BasePlugin` 基类，并实现 `initialize` 与 `execute` 两个抽象方法。

```python
from typing import Any, Dict
from backend.plugins.base_plugin import BasePlugin
from loguru import logger


class MyFirstPlugin(BasePlugin):
    name: str = "my-first-plugin"
    version: str = "1.0.0"
    description: str = "我的第一个插件"

    def initialize(self) -> bool:
        logger.info(f"插件 {self.name} 初始化成功")
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Any:
        input_text = kwargs.get("input", "")
        logger.info(f"插件执行，输入：{input_text}")
        return {
            "status": "success",
            "output": f"已处理：{input_text}"
        }
```

### 生命周期方法

`BasePlugin` 提供以下可重写的生命周期钩子：

| 方法 | 触发时机 | 返回值 |
|------|----------|--------|
| `initialize()` | 插件首次加载时 | bool |
| `execute(*args, **kwargs)` | 插件被调用执行时 | Any |
| `cleanup()` | 插件卸载时 | None |
| `validate()` | 注册前配置校验 | bool |
| `on_registered()` | 进入 registered 状态 | None |
| `on_loaded()` | 进入 loaded 状态 | None |
| `on_enabled()` | 进入 enabled 状态 | None |
| `on_disabled()` | 进入 disabled 状态 | None |
| `on_unloaded()` | 进入 unloaded 状态 | None |
| `on_error(error, from_state, to_state)` | 发生错误时 | None |

## 1.3 运行与调试

### 通过 REST API 注册插件

将插件目录放置在服务器可访问的路径后，调用以下接口进行注册：

```bash
# 从本地路径加载插件
curl -X POST http://localhost:8000/api/plugins/load \
  -H "Content-Type: application/json" \
  -d '{"path": "/absolute/path/to/plugins/my-first-plugin"}'
```

### 通过命令行工具

Open-AwA 提供了 CLI 工具用于插件管理：

```bash
# 列出所有已注册插件
python -m backend.plugins.cli.plugin_cli list

# 加载插件
python -m backend.plugins.cli.plugin_cli load --path ./plugins/my-first-plugin

# 启用插件
python -m backend.plugins.cli.plugin_cli enable --name my-first-plugin

# 禁用插件
python -m backend.plugins.cli.plugin_cli disable --name my-first-plugin
```

### 查看插件日志

系统使用 [loguru](https://github.com/Delgan/loguru) 进行日志管理，插件输出的日志会统一汇入系统日志流。

开发阶段建议在 `execute` 方法中使用 `logger.debug()` 输出详细信息：

```python
from loguru import logger

def execute(self, *args, **kwargs):
    logger.debug(f"收到参数：{kwargs}")
    # ...
```

### 前端调试面板

启动前端开发服务器后，进入「插件管理」页面可以：

- 查看所有已注册插件及其状态
- 手动触发插件启用、禁用
- 实时查看插件执行日志（PluginDebugPanel 组件）

### 常见启动错误排查

| 错误信息 | 原因 | 解决方法 |
|----------|------|----------|
| `Invalid manifest: missing required field 'name'` | manifest.json 缺少必填字段 | 检查 manifest.json 结构 |
| `Invalid extension: additional property ... is not allowed` | 扩展点声明包含非法字段 | 移除多余字段 |
| `Plugin does not have method 'execute'` | 插件类未实现 execute 方法 | 实现抽象方法 |
| `Execution exceeded Xs limit` | 插件执行超时 | 优化逻辑或申请更高超时配置 |
