# 完整插件系统 Spec

## Why
当前项目已有基础插件能力（上传、启停、执行），但缺少统一生命周期、依赖解析、安全隔离、热更新与工具链，无法支撑大规模插件生态与生产可用性目标。

## What Changes
- 建立插件生命周期状态机与幂等、回滚机制
- 增加三类来源加载（本地 ZIP、远程 URL、npm 包）与沙箱隔离
- 定义统一扩展点协议（不少于 8 类）与 JSON Schema/TypeScript 类型
- 增加依赖图构建、semver 解析、冲突诊断与升级建议
- 增加静态扫描 + 运行时拦截 + 权限授权/撤销
- 增加热更新双缓存与灰度发布能力
- 增加插件独立日志、调试面板与可观测性指标
- 提供官方 CLI（init/dev/typecheck/build/sign/publish）
- 交付开发文档与 3 个官方示例插件
- **BREAKING**: 插件清单（manifest）与运行权限模型升级为强约束校验

## Impact
- Affected specs: 插件生命周期、扩展点协议、安全权限、发布流程、可观测性
- Affected code:
  - backend/plugins/*
  - backend/api/routes/plugins.py
  - backend/db/models.py
  - frontend/src/pages/PluginsPage.tsx
  - frontend/src/plugins/*
  - frontend/src/services/api.ts

## ADDED Requirements

### Requirement: 生命周期状态机
系统 SHALL 提供插件状态机，支持 `registered/loaded/enabled/disabled/unloaded/error/updating`。

#### Scenario: 幂等启用
- **WHEN** 插件已处于 enabled 状态并再次执行启用
- **THEN** 返回成功且不重复执行副作用逻辑

#### Scenario: 失败回滚
- **WHEN** 插件在 `loaded -> enabled` 过程中抛出异常
- **THEN** 自动回滚至上一个稳定状态并记录审计日志

### Requirement: 多来源动态加载
系统 SHALL 支持本地 ZIP、远程 URL、npm 包三种来源安装与加载。

#### Scenario: 远程安装成功
- **WHEN** 用户提交合法远程插件 URL
- **THEN** 系统下载、验签、解包并注册插件

### Requirement: 沙箱隔离与资源限制
系统 SHALL 为每个插件提供独立沙箱与资源上限（内存、CPU、超时）。

#### Scenario: 禁止危险 API
- **WHEN** 插件尝试访问 DOM、Node 原生模块或敏感 API
- **THEN** 调用被阻断并生成安全事件日志

### Requirement: 统一扩展点协议
系统 SHALL 预置至少 8 类扩展点并统一使用 JSON Schema 与 TypeScript 类型声明。

#### Scenario: 清单校验通过
- **WHEN** 插件 manifest 声明扩展点与版本范围合法
- **THEN** 插件可注册对应扩展点处理器

### Requirement: 依赖与版本解析
系统 SHALL 构建依赖图，支持 semver 范围解析与冲突检测。

#### Scenario: 冲突诊断
- **WHEN** 两个插件依赖同一包但版本范围不相容
- **THEN** 返回可视化冲突报告与升级/降级建议

### Requirement: 权限授权与撤销
系统 SHALL 对危险操作执行白名单授权，支持细粒度撤销。

#### Scenario: 授权弹窗
- **WHEN** 插件首次申请高风险权限
- **THEN** 主应用弹窗征得用户同意后方可执行

### Requirement: 热更新与灰度发布
系统 SHALL 支持双缓存热更新与按用户/地域/版本灰度发布。

#### Scenario: 无感切换
- **WHEN** 新版本插件就绪
- **THEN** 在旧版本继续服务期间完成切换，失败自动回滚

### Requirement: 可观测性与调试
系统 SHALL 提供每插件独立日志、DEBUG 动态开关、API/事件/性能观测能力。

#### Scenario: 调试追踪
- **WHEN** 开启某插件 DEBUG 模式
- **THEN** 可实时查看该插件 API 调用与事件触发链路

### Requirement: 官方 CLI 与发布包规范
系统 SHALL 提供官方 CLI 并输出标准插件包：`@scope/name@version.zip`。

#### Scenario: 一键发布
- **WHEN** 开发者执行 publish 命令
- **THEN** 完成类型检查、打包、签名、上传流程

### Requirement: 文档与示例
系统 SHALL 提供开发手册、SDK 类型声明与 3 个官方示例插件。

#### Scenario: 快速上手
- **WHEN** 新开发者按手册执行示例
- **THEN** 可在本地完成插件创建、调试、打包、安装

## MODIFIED Requirements

### Requirement: 现有插件管理 API
现有插件安装/启停/卸载 API 需扩展为“状态机驱动 + 安全校验 + 审计日志”模型；返回结果包含状态、错误码、诊断信息。

## REMOVED Requirements

### Requirement: 非约束式插件清单解析
**Reason**: 弱校验无法保证安全与兼容性。
**Migration**: 所有插件需迁移到新版 manifest schema，并显式声明权限、扩展点、依赖范围。
