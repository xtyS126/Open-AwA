# 测试说明

本文档整理当前仓库已经存在的测试方式、常用命令与建议验证顺序，便于在修改代码或文档后快速回归。

## 1. 测试概览

当前仓库可见的测试形态包括：

- 后端 pytest 测试
- 前端 Vitest 单元测试
- 前端 TypeScript 类型检查
- 前端构建检查
- Playwright E2E 测试

对应文件可参考：

- [backend/tests](file:///d:/代码/Open-AwA/backend/tests)
- [frontend/src/__tests__](file:///d:/代码/Open-AwA/frontend/src/__tests__)
- [playwright.config.ts](file:///d:/代码/Open-AwA/frontend/playwright.config.ts#L1-L54)
- [package.json](file:///d:/代码/Open-AwA/frontend/package.json#L5-L14)

## 2. 后端测试

### 2.1 运行命令

```powershell
cd d:\代码\Open-AwA\backend
python -m pytest
```

### 2.2 当前可见测试文件

- [test_conversation_recorder.py](file:///d:/代码/Open-AwA/backend/tests/test_conversation_recorder.py)
- [test_extension_protocol.py](file:///d:/代码/Open-AwA/backend/tests/test_extension_protocol.py)
- [test_hot_update.py](file:///d:/代码/Open-AwA/backend/tests/test_hot_update.py)
- [test_memory_workflow_api.py](file:///d:/代码/Open-AwA/backend/tests/test_memory_workflow_api.py)
- [test_memory_workflow_edge_cases.py](file:///d:/代码/Open-AwA/backend/tests/test_memory_workflow_edge_cases.py)
- [test_memory_workflow_enhancements.py](file:///d:/代码/Open-AwA/backend/tests/test_memory_workflow_enhancements.py)
- [test_plugin_cli.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_cli.py#L12-L202)
- [test_plugin_lifecycle.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_lifecycle.py)
- [test_plugin_observability.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_observability.py)
- [test_plugin_performance_baseline.py](file:///d:/代码/Open-AwA/backend/tests/test_plugin_performance_baseline.py)
- [test_pricing_manager.py](file:///d:/代码/Open-AwA/backend/tests/test_pricing_manager.py)
- [test_vector_store_manager.py](file:///d:/代码/Open-AwA/backend/tests/test_vector_store_manager.py)

### 2.3 记忆与工作流定向回归

如果本次改动集中在长期记忆、向量检索、工作流引擎或对应 API，推荐优先运行：

```powershell
cd d:\代码\Open-AwA\backend
python -m pytest tests/test_vector_store_manager.py tests/test_memory_workflow_enhancements.py tests/test_memory_workflow_api.py tests/test_memory_workflow_edge_cases.py -q
```

这组测试覆盖：

- 向量写入、语义检索、用户隔离与归档过滤
- 长期记忆混合检索、归档、质量报告与统计
- 工作流引擎的工具步骤、技能步骤与条件分支
- 工作流与工具注册器的异常分支、占位符解析与兼容逻辑
- 记忆增强 API 与工作流 API 的创建、执行、状态查询

### 2.4 适合文档变更后的最小检查

如果这次只修改文档，一般至少可以确认：

- pytest 能正常启动
- 不存在因环境变化导致的基础错误

## 3. 前端单元测试

### 3.1 运行命令

```powershell
cd d:\代码\Open-AwA\frontend
npm run test
```

该命令来自：

- [package.json](file:///d:/代码/Open-AwA/frontend/package.json#L5-L14)

### 3.2 当前可见测试文件

- [ChatPage.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/ChatPage.test.tsx)
- [PluginDebugPanel.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/PluginDebugPanel.test.tsx)
- [PluginsPage.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/PluginsPage.test.tsx#L1-L130)
- [pluginTypes.test.ts](file:///d:/代码/Open-AwA/frontend/src/__tests__/pluginTypes.test.ts)

这些测试覆盖了聊天页、插件页及部分插件相关类型和调试面板。

## 4. 前端类型检查

```powershell
cd d:\代码\Open-AwA\frontend
npm run typecheck
```

该命令可以帮助尽快发现：

- 接口字段变更引起的类型不一致
- 测试 mock 与真实类型定义不匹配
- 页面参数与 API 封装签名不一致

## 5. 前端构建检查

```powershell
cd d:\代码\Open-AwA\frontend
npm run build
```

对于前端文档更新本身不一定必须执行，但如果你同时修改了页面或 API 类型，建议把构建检查加入回归流程。

## 6. E2E 测试

### 6.1 运行命令

```powershell
cd d:\代码\Open-AwA\frontend
npm run e2e
```

### 6.2 配置说明

Playwright 配置位于：

- [playwright.config.ts](file:///d:/代码/Open-AwA/frontend/playwright.config.ts#L1-L54)

当前配置会：

- 测试目录指向 `tests/e2e`
- 自动启动后端和前端开发服务
- 使用独立的 `openawa_e2e.db`
- 包含 Chromium、Firefox、Edge、Electron 项目

### 6.3 当前可见 E2E 文件

- [electron-smoke.spec.ts](file:///d:/代码/Open-AwA/frontend/tests/e2e/electron-smoke.spec.ts)
- [plugins-hot-update.spec.ts](file:///d:/代码/Open-AwA/frontend/tests/e2e/plugins-hot-update.spec.ts)

## 7. 推荐验证顺序

如果是代码改动，建议顺序如下：

1. 后端 pytest
2. 前端单元测试
3. 前端类型检查
4. 前端构建
5. E2E 测试

如果是纯文档改动，建议最小验证顺序如下：

1. 检查 Markdown 链接和路径是否正确
2. 人工抽样打开文档中的 `file:///` 链接
3. 如环境允许，可执行前端类型检查或一轮基础测试，确保仓库当前状态稳定

## 8. 本次文档相关的重点验证点

由于本次主要修改 README 与文档，建议重点验证：

- 根 README 中提到的路径和命令是否都存在
- `docs/README.md` 中所有索引链接可打开
- 插件开发文档中 CLI 命令与当前 `plugin_cli.py` 一致
- 架构文档中列出的页面、路由、模块与当前目录结构一致

## 9. 常见问题

### 9.1 E2E 测试启动慢

当前 Playwright 配置会同时拉起后端和前端服务，第一次运行或依赖未安装完整时会比较慢，这是正常现象。

### 9.2 前端测试通过但页面仍报接口错误

前端单元测试大量使用 mock，因此它们主要验证组件行为，不等价于后端联调成功。需要结合本地运行或 E2E 测试进一步确认。

### 9.3 文档改动是否一定要跑全量测试

从工程规范角度建议至少做最小验证；若时间和环境允许，仍推荐执行一轮基础测试，以确保仓库当前状态未被其他改动影响。
