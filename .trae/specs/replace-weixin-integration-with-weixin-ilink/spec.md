# 用 weixin-ilink 替换当前 weixin 集成 Spec

## Why
用户已经提供 `d:\代码\Open-AwA\插件\openclaw-weixin\完整精简版\weixin-ilink` 作为新的最佳实现，并要求以其 README 与源码为准嵌入当前项目。现有项目中的 weixin 相关实现来自多轮兼容修补，需规划一次以 `weixin-ilink` 为核心的整体替换，避免继续在旧链路上叠补逻辑。

## What Changes
- 以 `weixin-ilink/README.md` 描述的 SDK 能力、登录流程与 API 约定为唯一接入基线，重新设计当前项目中的 weixin 集成边界
- 用 `weixin-ilink` 的二维码登录、消息拉取、消息发送、配置获取、上传能力映射替换当前后端适配层中的旧实现
- 重构前端通讯页与 API 契约，使其消费 `weixin-ilink` 风格的登录状态与凭据字段
- 清理当前项目中与新方案冲突或已被替代的旧 weixin 逻辑、测试与冗余兼容代码
- 补齐针对 `weixin-ilink` 接入后的回归测试、类型检查与运行验证
- **BREAKING** 当前项目内部依赖旧 weixin 字段名、旧状态名、旧适配器行为的代码将调整为 `weixin-ilink` 语义
- **BREAKING** 与新方案冲突的旧 weixin 集成代码将被替换或移除，而不是继续并存

## Impact
- Affected specs: weixin 二维码登录、weixin Skill 适配、通讯页状态机、消息轮询与发送、配置持久化与健康检查
- Affected code: `backend/skills/weixin_skill_adapter.py`、`backend/api/routes/skills.py`、`frontend/src/pages/CommunicationPage.tsx`、`frontend/src/services/api.ts`、相关 weixin 测试文件、可能涉及的 weixin 配置持久化代码

## ADDED Requirements
### Requirement: 以 weixin-ilink README 为基线的接入方案
系统 SHALL 直接依据 `weixin-ilink/README.md` 中公开说明的登录、客户端构造、轮询、发送与辅助 API 能力，建立当前项目中的 weixin 集成方案。

#### Scenario: 解析 README 与源码能力
- **WHEN** 开发者审阅 `weixin-ilink` 的 README、导出入口与核心源码
- **THEN** 系统应形成一套与 `ILinkClient`、`loginWithQR`、低阶 API 函数一致的接入映射
- **AND** 不再把旧 openclaw-weixin 兼容逻辑作为主要依据

### Requirement: 用 weixin-ilink 替换二维码登录闭环
系统 SHALL 使用 `weixin-ilink` 的二维码登录模型替换当前项目中的旧二维码开始、轮询、超时与成功回填实现。

#### Scenario: 用户发起二维码登录
- **WHEN** 用户在当前项目中发起微信登录
- **THEN** 系统应按 `loginWithQR` 的语义生成二维码展示与状态推进
- **AND** 登录成功后返回并保存 `botToken`、`accountId`、`baseUrl` 与可用的 `userId`

#### Scenario: 登录状态推进与超时
- **WHEN** 登录过程中出现 waiting、scanned、expired、refreshing、timeout 或失败
- **THEN** 前后端状态应与 `weixin-ilink` 的状态语义一致
- **AND** 用户界面不应继续依赖旧状态名或旧推断逻辑

### Requirement: 用 weixin-ilink 客户端替换消息能力实现
系统 SHALL 使用 `ILinkClient` 或其等价低阶 API 语义替换当前项目中的消息拉取、发送消息、获取配置与上传 URL 相关实现。

#### Scenario: 拉取更新与发送消息
- **WHEN** 后端执行消息轮询、发送文本或发送媒体
- **THEN** 请求参数、超时语义、游标更新与返回结构应与 `weixin-ilink` 保持一致
- **AND** 当前项目应保留必要的本地状态持久化以支撑重启恢复

### Requirement: 清理旧 weixin 集成代码
系统 SHALL 清理当前项目中已被 `weixin-ilink` 替换的旧适配逻辑、旧字段映射、旧状态兼容分支与旧测试断言。

#### Scenario: 替换完成后清理旧实现
- **WHEN** 新方案已覆盖登录与消息能力
- **THEN** 与新方案冲突的旧 weixin 代码应被删除或重写
- **AND** 不应保留会误导后续维护者的重复实现

### Requirement: 替换后的系统验证
系统 SHALL 为新的 `weixin-ilink` 集成提供可执行验证，确保替换后功能可用且无关键回归。

#### Scenario: 运行验证
- **WHEN** 替换完成
- **THEN** 应运行相关后端测试、前端测试、类型检查与必要构建校验
- **AND** 回归步骤应覆盖二维码登录、凭据回填、消息拉取与消息发送的关键路径

## MODIFIED Requirements
### Requirement: 当前项目的 weixin 集成实现
当前项目的 weixin 集成 SHALL 以 `d:\代码\Open-AwA\插件\openclaw-weixin\完整精简版\weixin-ilink` 为新的主要实现基线。现有项目中的 weixin 后端适配、二维码接口、前端通讯页与相关测试，需要围绕该基线完成替换，而不是继续沿用旧 openclaw-weixin 推断式实现。

## REMOVED Requirements
### Requirement: 旧 weixin 兼容链路继续保留为主实现
**Reason**: 用户已明确要求把 `weixin-ilink` 嵌入当前项目，并删除当前旧实现；继续保留旧链路作为主实现会增加维护成本并与目标冲突。
**Migration**: 逐步识别当前 weixin 相关入口、状态机、适配器与测试，将其替换为 `weixin-ilink` 风格实现，并在验证通过后移除旧逻辑。