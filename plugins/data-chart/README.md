# data-chart 插件

演示 Open-AwA API 拦截、权限申请与数据提供者扩展点的图表数据插件。

## 功能

- 通过 `network:http` 权限发起 HTTP 请求，从远端 API 拉取指标数据
- 注册 `middleware` 扩展点，拦截 `/api/chart/*` 路由并注入认证头
- 注册 `data_provider` 扩展点，为前端图表组件提供结构化数据
- 未配置远端 API 时自动降级为模拟数据模式，方便本地开发

## 演示的 API 能力

| 能力 | 说明 |
|------|------|
| 权限申请 | 在 manifest.json 中声明 `network:http`，使用 `httpx` 发起 HTTP 请求 |
| API 拦截 | 注册 `middleware` 扩展点，对指定路径前缀的请求注入自定义 HTTP 头 |
| 数据提供者 | 注册 `data_provider` 扩展点，向其他模块输出结构化图表数据 |
| 沙箱兼容 | 所有外部 IO 操作均使用 `httpx`（支持 async），符合沙箱执行模型 |

## 安装与配置

```bash
curl -X POST http://localhost:8000/api/plugins/load \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/path/to/plugins/data-chart",
    "config": {
      "api_base_url": "https://metrics.example.com",
      "api_key": "your-api-key-here",
      "default_chart_type": "line",
      "max_data_points": 200
    }
  }'
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `api_base_url` | string | `""` | 远端数据源 Base URL，留空则使用模拟数据 |
| `api_key` | string | `""` | API 认证密钥，通过 Bearer Token 传递 |
| `default_chart_type` | string | `"line"` | 默认图表类型，可选：`line`、`bar`、`pie` |
| `max_data_points` | integer | `500` | 单次查询返回的最大数据点数量 |

## 使用示例

### 拉取图表数据

```bash
curl -X POST http://localhost:8000/api/plugins/data-chart/execute \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "action": "fetch_chart_data",
      "chart_type": "line",
      "metric": "requests",
      "interval": "24h"
    }
  }'
```

返回（模拟数据模式）：

```json
{
  "status": "success",
  "chart_type": "line",
  "metric": "requests",
  "interval": "24h",
  "data_points": [
    {"index": 0, "value": 13, "label": "t0"},
    {"index": 1, "value": 20, "label": "t1"}
  ],
  "source": "mock"
}
```

### API 拦截中间件

当请求路径以 `/api/chart/` 开头时，中间件自动注入：

- `X-Chart-Token`：插件配置的 `api_key`
- `X-Plugin-Version`：当前插件版本号

## 权限

| 权限 | 原因 |
|------|------|
| `network:http` | 使用 `httpx` 向远端数据源发起 HTTP GET 请求 |

## 文件结构

```
data-chart/
  manifest.json    # 插件元数据，声明 network:http 权限与三类扩展点
  src/
    index.py       # 插件主入口，包含 DataChartPlugin 类
  README.md        # 本文件
```
