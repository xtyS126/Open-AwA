# 第一章：快速开始

本章介绍如何基于当前仓库中的插件 CLI、基类和示例插件快速创建一个可被 Open-AwA 识别的插件。

## 1. 环境准备

建议环境：

| 项目 | 建议版本 |
| --- | --- |
| Python | 3.11 及以上 |
| Node.js | 18 及以上 |
| npm | 9 及以上 |

如果你只开发后端插件，通常只需要 Python 环境即可。

安装后端依赖：

```powershell
cd d:\代码\Open-AwA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

插件 CLI 位于：

- [plugin_cli.py](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L11-L166)

## 2. 插件最小目录结构

当前仓库的 CLI 与示例插件表明，一个插件目录通常至少包含：

```text
my-plugin/
├─ manifest.json
├─ README.md
├─ LICENSE
└─ src/
   └─ index.py
```

其中：

- `manifest.json`：插件元数据与扩展点声明
- `src/index.py`：插件主实现文件
- `README.md`、`LICENSE`：CLI 打包校验时会一并处理

CLI `build` 会优先打包 `dist/` 目录；如果没有该目录，会写入占位文件 `dist/.gitkeep` 到 zip 包中。

参考代码：

- [plugin_cli.py](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L58-L94)

## 3. 使用 CLI 初始化插件

当前 CLI 的 `init` 命令要求显式传入 `--name`：

```powershell
cd d:\代码\Open-AwA\backend
python -m plugins.cli.plugin_cli init ..\plugins\my-plugin --name my-plugin --version 1.0.0 --author your-name --description "示例插件"
```

生成结果来自：

- [cmd_init](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L16-L55)

命令执行后会生成：

- `manifest.json`
- `src/index.py`
- `README.md`
- `LICENSE`

## 4. manifest.json 的当前格式

根据 CLI 初始化逻辑与扩展点校验器，插件清单至少应包含：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "pluginApiVersion": "1.0.0",
  "description": "示例插件",
  "author": "your-name",
  "permissions": [],
  "extensions": [
    {
      "point": "tool",
      "name": "my-plugin",
      "version": "1.0.0"
    }
  ]
}
```

当前代码里可以确认的扩展点类型见：

- [ExtensionPointType](file:///d:/代码/Open-AwA/backend/plugins/extension_protocol.py#L8-L16)

## 5. 编写插件实现

需要注意的是：

- 真正被后端插件系统动态加载的类，需要继承 `BasePlugin`
- CLI 生成的 `src/index.py` 只是一个最简占位文件，通常需要你手工改造成类实现

`BasePlugin` 定义见：

- [base_plugin.py](file:///d:/代码/Open-AwA/backend/plugins/base_plugin.py#L5-L58)

一个最小可用示例：

```python
from typing import Any
from backend.plugins.base_plugin import BasePlugin


class MyPlugin(BasePlugin):
    name = "my-plugin"
    version = "1.0.0"
    description = "示例插件"

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Any:
        return {
            "status": "success",
            "echo": kwargs,
        }
```

## 6. 参考示例插件

建议优先阅读这几个插件：

- [hello-world](file:///d:/代码/Open-AwA/plugins/hello-world/src/index.py)
- [theme-switcher](file:///d:/代码/Open-AwA/plugins/theme-switcher/src/index.py#L28-L145)
- [data-chart](file:///d:/代码/Open-AwA/plugins/data-chart/src/index.py#L9-L205)

它们分别展示了：

- 基础执行逻辑
- 工具描述输出
- 配置读取
- 模拟数据模式
- API 拦截和数据提供场景

## 7. 打包、校验、签名

### 打包

```powershell
cd d:\代码\Open-AwA\backend
python -m plugins.cli.plugin_cli build d:\代码\Open-AwA\plugins\my-plugin -o d:\代码\Open-AwA\dist
```

### 校验

注意：当前 `validate` 命令接收的是 zip 文件路径。

```powershell
python -m plugins.cli.plugin_cli validate d:\代码\Open-AwA\dist\my-plugin@1.0.0.zip
```

### 签名

```powershell
python -m plugins.cli.plugin_cli sign d:\代码\Open-AwA\dist\my-plugin@1.0.0.zip
```

相关代码：

- [cmd_build](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L58-L95)
- [cmd_validate](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L97-L140)
- [cmd_sign](file:///d:/代码/Open-AwA/backend/plugins/cli/plugin_cli.py#L143-L166)

## 8. 在系统中导入与执行

当前前后端提供的常见接入方式：

### 方式一：前端插件管理页面导入

前端插件页支持上传 zip：

- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L127-L150)

后端上传接口：

- [upload_plugin](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L371-L421)

### 方式二：通过插件管理 API 执行

插件执行接口：

- [execute_plugin](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L203-L245)

## 9. 调试建议

当前仓库提供两类调试方式：

1. 后端日志
2. 前端插件调试面板

插件日志相关接口：

- [get_plugin_logs](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L500-L519)

前端调试面板入口：

- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L213-L241)

## 10. 本章小结

如果你只想尽快跑通一个插件，推荐最短路径：

1. 用 CLI 初始化目录
2. 把 `src/index.py` 改成继承 `BasePlugin` 的类
3. 声明至少一个扩展点
4. 打包成 zip
5. 在插件管理页面导入并执行
