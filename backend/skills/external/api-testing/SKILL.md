---
name: api-testing
description: Open-AwA 项目专属 API 自动化测试 Skill，支持批量调用所有测试 API、自动断言校验、生成标准化测试报告
---

# API 自动化测试 Skill

## 概述

`api-testing` 是 Open-AwA 项目专属的自动化 API 测试 Skill，通过 YAML 配置定义测试用例，基于 `httpx` 异步引擎批量执行 HTTP 请求，集成断言校验和异常处理机制，最终生成标准化的 Markdown/JSON 测试报告。

### 核心特性

- **声明式测试用例**：通过 YAML 配置文件定义测试用例，无需编写代码
- **6 种断言类型**：status_code / json_path / response_time / body_contains / header_check / schema_match
- **批量并发执行**：基于 `asyncio.Semaphore` 的并发控制，默认 5 并发
- **完整异常处理**：自动捕获并分类网络错误、超时、HTTP 错误等
- **双格式报告**：Markdown（人类可读）+ JSON（机器可读）
- **认证自动管理**：支持 Token 直传或用户名密码自动登录获取

## 目录结构

```
backend/skills/external/api-testing/
├── SKILL.md                    # 本文档
├── skill.yaml                  # Skill 元数据
├── LICENSE.txt                 # MIT 许可证
├── config/
│   └── test_cases.yaml         # 测试用例定义（覆盖 24 个 API 模块）
├── core/
│   ├── __init__.py             # 入口模块（独立脚本 + SkillEngine 适配）
│   ├── models.py               # Pydantic 数据模型
│   ├── assertions.py           # 断言引擎
│   ├── executor.py             # 测试执行器
│   ├── reporter.py             # 报告生成器
│   └── exception_handler.py   # 异常分类与处理
├── tests/
│   ├── __init__.py
│   ├── test_assertions.py      # 断言引擎单元测试（29 个用例）
│   ├── test_exception_handler.py  # 异常处理单元测试（14 个用例）
│   └── test_reporter.py        # 报告生成器单元测试（13 个用例）
└── reports/                    # 测试报告输出目录
    └── .gitkeep
```

## 安装与配置

### 安装方式一：作为 Skill 安装（推荐）

通过 Open-AwA 的 Skill 管理 API 安装：

```bash
# 将整个 api-testing 目录打包为 ZIP
cd backend/skills/external
zip -r api-testing.zip api-testing/

# 通过 API 安装
curl -X POST http://localhost:8000/skills/install-from-package \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@api-testing.zip"
```

### 安装方式二：直接使用（无需安装）

由于 Skill 目录已在项目中，可以直接通过 Python 导入使用：

```python
import sys
sys.path.insert(0, "backend/skills/external/api-testing")

from core import load_test_cases_from_yaml, run_api_tests, build_and_save_report
```

### 配置说明

执行配置可通过 `TestExecutionConfig` 设置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `base_url` | `http://127.0.0.1:8000` | API 服务基础 URL |
| `auth_token` | `None` | 认证 Token（直接提供） |
| `auth_username` | `None` | 登录用户名（自动获取 Token） |
| `auth_password` | `None` | 登录密码 |
| `default_timeout_seconds` | 30 | 默认请求超时（秒） |
| `max_concurrency` | 5 | 最大并发数 |
| `modules_filter` | `[]` | 指定执行的模块列表 |
| `tags_filter` | `[]` | 按标签筛选 |
| `report_formats` | `["markdown", "json"]` | 报告输出格式 |
| `report_output_dir` | `reports` | 报告输出目录 |

## 使用方法

### 方式一：命令行独立运行

```bash
cd backend/skills/external/api-testing

# 使用默认配置运行全部测试
python -m core

# 指定服务器地址和 Token
python -m core --base-url http://localhost:8000 --auth-token YOUR_TOKEN

# 使用用户名密码自动登录
python -m core --base-url http://localhost:8000 \
  --auth-username admin --auth-password admin123

# 仅运行 system 和 auth 模块
python -m core --modules system auth

# 高并发模式 + 详细日志
python -m core --concurrency 10 --verbose
```

### 方式二：Python API 调用

```python
import asyncio
import sys
sys.path.insert(0, "backend/skills/external/api-testing")

from core import (
    load_test_cases_from_yaml,
    run_api_tests,
    build_and_save_report,
    TestExecutionConfig,
    TestExecutor,
)

async def main():
    # 1. 加载测试用例
    test_cases = load_test_cases_from_yaml("config/test_cases.yaml")

    # 2. 构建执行配置
    config = TestExecutionConfig(
        base_url="http://127.0.0.1:8000",
        auth_token="YOUR_TOKEN",
        max_concurrency=5,
        verbose=True,
    )

    # 3. 执行测试
    executor = TestExecutor(config)
    try:
        results = await executor.execute_all(test_cases)
    finally:
        await executor.close()

    # 4. 生成报告
    reports = build_and_save_report(results, output_dir="reports", config=config)
    print(f"报告已保存: {reports}")

asyncio.run(main())
```

### 方式三：在 SkillEngine 中执行

安装 Skill 后，通过 `/skills/{skill_id}/execute` API 触发：

```bash
curl -X POST http://localhost:8000/skills/{skill_id}/execute \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "base_url": "http://127.0.0.1:8000",
      "modules_filter": ["system", "auth"]
    },
    "context": {}
  }'
```

## 测试用例编写

### YAML 配置格式

在 `config/test_cases.yaml` 中按模块分组定义测试用例：

```yaml
modules:
  # 模块名
  system:
    - id: "sys-001"                    # 用例唯一标识
      name: "服务健康检查"              # 用例名称
      module: "system"                 # 所属模块
      description: "验证 /health 端点"  # 用例描述
      method: "GET"                    # HTTP 方法
      path: "/health"                  # API 路径
      requires_auth: false             # 是否需认证
      timeout_seconds: 10              # 超时秒数
      priority: "high"                 # 优先级：high/normal/low
      tags: ["smoke", "health"]        # 标签
      assertions:                      # 断言规则
        - type: "status_code"          # 断言类型
          expected: 200                # 期望值
          description: "返回 200 状态码"  # 断言说明
        - type: "json_path"            # JSON 字段校验
          field: "status"              # 字段路径（点号分隔）
          expected: "ok"               # 期望值
          operator: "eq"               # 运算符
```

### 支持的断言类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `status_code` | HTTP 状态码 | `{type: status_code, expected: 200}` |
| `json_path` | JSON 字段取值 | `{type: json_path, field: "data.id", expected: 1, operator: "gt"}` |
| `response_time` | 响应耗时 | `{type: response_time, expected: 1000, operator: "lte"}` |
| `body_contains` | 响应体文本包含 | `{type: body_contains, expected: "success"}` |
| `header_check` | 响应头字段 | `{type: header_check, field: "content-type", expected: "json", operator: "contains"}` |
| `schema_match` | 结构类型匹配 | `{type: schema_match, expected: {"data": "dict", "data.id": "int"}}` |

### 支持的运算符

| 运算符 | 说明 |
|--------|------|
| `eq` / `ne` | 等于 / 不等于 |
| `gt` / `lt` / `gte` / `lte` | 大于 / 小于 / 大于等于 / 小于等于 |
| `contains` / `not_contains` | 包含 / 不包含 |
| `regex` | 正则匹配 |
| `in` / `not_in` | 在列表中 / 不在列表中 |
| `is_none` / `is_not_none` | 为 None / 非 None |

### Schema 类型描述

在 `schema_match` 断言中，支持的 Python 类型描述：

| 类型描述 | 对应 Python 类型 |
|----------|-----------------|
| `any` | 任意非 None 值 |
| `str` / `int` / `float` / `bool` | 基本类型 |
| `non_empty_str` | 非空字符串 |
| `positive_int` | 正整数 |
| `dict` / `list` | 字典 / 列表 |
| `none` / `null` | None |

## 测试报告

### Markdown 报告结构

```markdown
# API 自动化测试报告

**报告ID**: `abc12345`
**生成时间**: 2026-01-15T12:00:00+00:00
**目标服务器**: http://127.0.0.1:8000

## ✅ 总体通过率: 95.0%

## 📊 执行摘要
| 指标 | 数值 |
|------|------|
| 总用例数 | 28 |
| ✅ 通过 | 25 |
| ❌ 失败 | 1 |
| 💥 错误 | 1 |
...

## 📦 模块分布
...

## 🔴 失败与错误详情
### 1. ❌ 断言失败 — 无认证应 401
- **用例ID**: `auth-002`
- **模块**: auth
- **耗时**: 5ms
- **错误信息**: 状态码校验失败: 期望 401, 实际 200
...
```

### JSON 报告结构

完整的结构化数据，包含所有请求参数、响应数据、断言结果，适合集成到 CI/CD 流水线。

## 运行单元测试

```bash
cd backend/skills/external/api-testing
python -m pytest tests/ -v
```

## 已覆盖的 API 模块

当前 YAML 配置覆盖了全部 24 个 API 路由模块：

| 模块 | 测试用例数 | 覆盖场景 |
|------|-----------|---------|
| system | 2 | 健康检查、全量诊断 |
| auth | 2 | CSRF Token、未认证 401 |
| conversation | 2 | 列表查询、创建会话 |
| chat | 1 | 消息列表 |
| skills | 2 | 技能列表、不存在资源 404 |
| plugins | 2 | 插件列表、已加载插件 |
| memory | 1 | 会话记忆 |
| user | 1 | 用户偏好 |
| experiences | 1 | 经验列表 |
| prompts | 1 | 提示词列表 |
| tools | 1 | 工具列表 |
| workflows | 1 | 工作流列表 |
| models | 2 | 模型配置、供应商列表 |
| billing | 1 | 计费概览 |
| scheduled_tasks | 1 | 定时任务列表 |
| security | 1 | 权限查询 |
| mcp | 1 | MCP 状态 |
| weixin | 1 | 微信配置 |
| marketplace | 1 | 插件市场 |
| subagents | 1 | 子 Agent 列表 |
| task_runtime | 1 | 运行时状态 |
| behavior | 1 | 行为日志 |
| logs | 1 | 系统日志 |
| test_runner | 1 | 场景列表 |

## 扩展测试用例

要添加新的测试用例，编辑 `config/test_cases.yaml`，在对应模块下追加新的用例定义即可。无需修改任何代码。

## CI/CD 集成

```yaml
# 示例: GitHub Actions 中使用
- name: Run API Tests
  run: |
    cd backend/skills/external/api-testing
    python -m core \
      --base-url http://localhost:8000 \
      --auth-token ${{ secrets.TEST_AUTH_TOKEN }} \
      --output-dir reports/
- name: Upload Test Report
  uses: actions/upload-artifact@v4
  with:
    name: api-test-reports
    path: backend/skills/external/api-testing/reports/
```
