# 修复 Vite HTTP 代理 ECONNREFUSED 错误 Spec

## Why
前端 Vite 开发服务器运行时，HTTP 代理请求到后端 API（/api/auth/login、/api/billing/providers）失败，报错 `ECONNREFUSED`，表示后端服务（localhost:8000）未启动或无法连接。需要系统性排查并确保前后端联调正常。

## What Changes
- 确认后端服务启动状态与端口配置
- 验证后端服务可正常启动
- 提供前后端联调启动方案
- 验证修复结果

## Impact
- Affected specs: 无直接影响
- Affected code: 无代码修改，仅运行时配置验证

## 根因分析

### 错误现象
```
[vite] http proxy error: /api/auth/login
AggregateError [ECONNREFUSED]:
    at internalConnectMultiple (node:net:1134:18)
    at afterConnectMultiple (node:net:1715:7)
```

### 根因定位
1. **前端配置正确**：Vite 配置将 `/api` 代理到 `http://localhost:8000`
2. **后端未运行**：`ECONNREFUSED` 表示目标端口无服务监听
3. **请求路径**：前端初始化时自动调用 `/api/auth/login` 和 `/api/billing/providers`

### 验证步骤
1. 检查端口 8000 是否有服务监听
2. 尝试启动后端服务
3. 验证后端健康检查接口
4. 重新测试前端代理请求

## ADDED Requirements

### Requirement: 后端服务可正常启动
系统必须确保后端服务能够在端口 8000 正常启动并响应请求。

#### Scenario: 后端服务启动成功
- **WHEN** 执行 `python main.py` 或 `uvicorn main:app --host 0.0.0.0 --port 8000`
- **THEN** 服务应在端口 8000 监听，且 `/health` 返回 `{"status": "healthy"}`

#### Scenario: 前端代理请求成功
- **WHEN** 后端服务运行中，前端发起 `/api/auth/login` 请求
- **THEN** Vite 代理应成功转发请求，不再报 `ECONNREFUSED`

### Requirement: 前后端联调环境就绪
系统必须提供清晰的前后端联调启动指南。

#### Scenario: 同时启动前后端
- **WHEN** 用户需要开发调试
- **THEN** 应能按文档指引同时启动后端（8000）和前端（5173）

## MODIFIED Requirements
无

## REMOVED Requirements
无
