# hello-world 插件

最简示例插件，演示 Open-AwA 插件的基本结构、生命周期钩子与日志输出。

## 功能

- 向指定名称的用户输出问候消息
- 演示 `initialize`、`execute`、`cleanup`、`on_enabled`、`on_disabled` 生命周期钩子
- 演示 `get_tools` 方法的标准格式

## 安装与配置

将本目录复制到服务器后，通过 API 加载：

```bash
curl -X POST http://localhost:8000/api/plugins/load \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/plugins/hello-world"}'
```

### 可选配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `greeting` | string | `"你好"` | 问候语前缀 |

示例配置：

```json
{
  "path": "/path/to/plugins/hello-world",
  "config": {
    "greeting": "Hello"
  }
}
```

## 使用示例

调用 `say_hello` 工具：

```bash
curl -X POST http://localhost:8000/api/plugins/hello-world/execute \
  -H "Content-Type: application/json" \
  -d '{"params": {"name": "Alice"}}'
```

返回结果：

```json
{
  "status": "success",
  "message": "你好，Alice！",
  "plugin": "hello-world",
  "version": "1.0.0"
}
```

## 权限

本插件不需要任何特殊权限。

## 文件结构

```
hello-world/
  manifest.json    # 插件元数据
  src/
    index.py       # 插件主入口，包含 HelloWorldPlugin 类
  README.md        # 本文件
```
