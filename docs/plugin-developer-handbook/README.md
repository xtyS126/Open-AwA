# Open-AwA 插件开发者手册

本手册面向希望为 Open-AwA 平台开发插件的开发者，提供从环境搭建到发布上线的完整指引。

## 目录

| 章节 | 内容 |
|------|------|
| [1. 快速入门](./1-getting-started.md) | 环境准备、创建第一个插件、运行与调试流程 |
| [2. API 参考](./2-api-reference.md) | 核心API、扩展点API、存储API、事件API、权限API |
| [3. 最佳实践](./3-best-practices.md) | 安全规范、性能优化、用户体验 |
| [4. 常见问题](./4-faq.md) | 开发过程中的常见问题与解答 |

## 示例插件

仓库 `plugins/` 目录下提供了三个开箱即用的示例插件：

- [hello-world](../../plugins/hello-world/README.md) — 最简示例，演示插件生命周期与日志输出
- [theme-switcher](../../plugins/theme-switcher/README.md) — 演示存储 API 与 UI 扩展点
- [data-chart](../../plugins/data-chart/README.md) — 演示 API 拦截与权限申请

## 插件系统概述

Open-AwA 的插件系统基于以下核心概念：

- **manifest.json**：插件元数据描述文件，声明插件名称、版本、权限与扩展点
- **BasePlugin**：所有插件必须继承的基类，定义了生命周期方法
- **ExtensionPoint**：插件向系统注册能力的接入口，支持 tool、hook、command、route、event_handler、scheduler、middleware、data_provider 八种类型
- **PluginSandbox**：插件运行时隔离沙箱，限制超时、内存与 CPU 使用
- **PluginStateMachine**：管理插件状态流转（registered → loaded → enabled → disabled → unloaded）

## 快速参考：插件状态流转

```
registered
    |
    v
  loaded  <----+
    |           |
    v           |
  enabled       | (热更新)
    |     ------+
    v
  disabled
    |
    v
  unloaded
```

任何状态均可转入 `error` 状态；`error` 状态可恢复至 `loaded` 或 `unloaded`。
