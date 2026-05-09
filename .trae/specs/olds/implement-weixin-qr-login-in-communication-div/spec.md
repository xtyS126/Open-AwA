# 微信通讯页二维码登录与登录后能力 Spec

## Why
当前通讯页仅支持手动填写 account_id/token，无法直接发起微信扫码登录，也缺少登录后账号态管理，导致接入流程割裂且易出错。需要在现有 div 区块内补齐从“获取二维码”到“登录后可运维”的完整闭环。

## What Changes
- 在通讯页现有微信配置 div 内新增二维码登录流程：获取二维码、轮询登录状态、过期刷新、登录成功回填配置。
- 后端新增二维码登录相关接口，桥接 openclaw-weixin 的 `loginWithQrStart/loginWithQrWait` 能力。
- 在登录后区域新增账号能力：展示当前登录账号信息、连接状态检测、重新登录、退出登录。
- 调整前端状态机与错误提示，覆盖 wait/scaned/confirmed/expired/timeout 等状态。
- 保留现有“手动配置 + 保存配置 + 健康检查”能力并与扫码登录结果兼容。

## Impact
- Affected specs: 通讯配置页（微信 Clawbot）交互规范、技能配置保存与健康检查流程
- Affected code: `frontend/src/pages/CommunicationPage.tsx`、`frontend/src/pages/CommunicationPage.css`、`frontend/src/services/api.ts`、`backend/api/routes/skills.py`、相关前后端测试

## ADDED Requirements
### Requirement: 二维码登录获取与状态跟踪
系统 SHALL 在通讯页提供二维码登录入口，用户可在页面内完成二维码获取与扫码状态跟踪。

#### Scenario: 成功获取二维码
- **WHEN** 用户点击“获取二维码登录”
- **THEN** 系统调用后端二维码开始接口并展示二维码图片
- **AND** 页面保存 `session_key` 以用于后续状态轮询

#### Scenario: 扫码状态变化可见
- **WHEN** 二维码登录处于等待、已扫码、已确认、已过期状态
- **THEN** 页面显示对应中文状态与下一步提示
- **AND** 已过期时允许用户一键刷新二维码并继续流程

#### Scenario: 登录成功自动回填
- **WHEN** 后端返回登录确认且包含账号凭据
- **THEN** 页面自动回填 `account_id`、`token`、`base_url`
- **AND** 同步展示“已登录”状态与账号标识信息

### Requirement: 登录后能力区块
系统 SHALL 在同一 div 内提供登录后的管理能力，覆盖常见运维操作。

#### Scenario: 登录后可执行连接运维
- **WHEN** 用户已登录微信账号
- **THEN** 可在页面内执行“保存配置”“测试连接”“重新登录”“退出登录”
- **AND** 每个操作均显示进行中状态、成功提示和失败原因

#### Scenario: 退出登录后状态一致
- **WHEN** 用户执行退出登录
- **THEN** 后端清理当前账号凭据并返回成功
- **AND** 前端清空敏感字段并恢复到“未登录”状态

## MODIFIED Requirements
### Requirement: 通讯配置表单交互
现有通讯配置页 SHALL 从“纯手动配置”升级为“扫码优先 + 手动兜底”的统一交互：
- 扫码成功后自动填充并允许用户二次编辑后保存。
- 未扫码时仍支持手动输入并保存。
- 健康检查始终基于当前表单值执行。

## REMOVED Requirements
### Requirement: 通讯页仅支持手动输入凭据
**Reason**: 该模式依赖外部终端流程，配置门槛高且易发生字段错误。  
**Migration**: 保留手动输入作为兜底路径，但默认主路径改为页面内二维码登录。
