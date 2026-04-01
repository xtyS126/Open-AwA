# 解析 open-weixin 源码并重构现有集成 Spec

## Why
当前项目里的 weixin 通讯与适配实现已经具备基础能力，但部分行为是基于历史推断逐步修补出来的。用户要求以 `d:\代码\Open-AwA\插件\openclaw-weixin\源码` 为唯一基准重新解析插件源码，并据此重构现有项目文件，避免继续依赖二手解析结论。

## What Changes
- 以 open-weixin 源码中的真实入口、配置结构、二维码登录协议、消息发送与拉取约定为准，重新梳理当前项目的 weixin 集成边界
- 重构后端 weixin 适配层、二维码登录接口和前端通讯页，使字段、状态机、错误语义与上游源码保持一致
- 清理当前实现中与源码不一致的推断式兼容逻辑，保留必要的本地封装但统一对外返回结构
- 补齐基于源码行为的回归测试，覆盖健康检查、二维码登录、消息能力与异常路径
- **BREAKING** 若当前项目对外返回的部分 weixin 临时字段与上游真实语义不一致，需要调整为源码对齐后的字段与状态命名

## Impact
- Affected specs: weixin Skill 适配、通讯页二维码登录、weixin 配置与健康检查、消息收发协议
- Affected code: `backend/skills/weixin_skill_adapter.py`、`backend/api/routes/skills.py`、`frontend/src/pages/CommunicationPage.tsx`、`frontend/src/services/api.ts`、相关测试文件

## ADDED Requirements
### Requirement: 以源码为准的 weixin 协议映射
系统 SHALL 直接依据 open-weixin 源码中的真实实现，建立当前项目与插件之间的字段映射、状态机映射、错误语义映射与运行前提约束。

#### Scenario: 从源码提取协议约束
- **WHEN** 开发者分析 `openclaw-weixin` 源码中的登录、API、配置与运行入口
- **THEN** 系统应形成可执行的字段映射与状态定义，并用于指导后续重构
- **AND** 不再以历史推测或第三方解析结果作为主要依据

### Requirement: 二维码登录流程与源码一致
系统 SHALL 让当前项目中的二维码生成、轮询、确认成功、过期处理、超时处理和重试行为与 open-weixin 源码语义一致。

#### Scenario: 获取二维码并等待扫码
- **WHEN** 用户在通讯页发起微信二维码登录
- **THEN** 后端返回的二维码字段应对应源码中的真实二维码内容
- **AND** 前端应按源码语义展示二维码与等待状态

#### Scenario: 扫码后的中间态与成功态
- **WHEN** 上游返回已扫码、中间跳转、确认成功或过期等状态
- **THEN** 当前项目应映射为稳定且可识别的前后端状态
- **AND** 成功后应正确回填账号、token、base_url 等必要配置

### Requirement: Skill 适配行为与源码能力对齐
系统 SHALL 依据源码中真实可用的 API 能力重构 weixin Skill 适配层，确保配置校验、请求构造、错误处理与返回结构一致。

#### Scenario: 执行健康检查或消息能力
- **WHEN** Skill 引擎调用 weixin 适配层执行健康检查、发送消息或拉取更新
- **THEN** 适配层应按源码约束构造请求与解析响应
- **AND** 对缺配置、缺依赖、网络异常和上游异常返回结构化错误

### Requirement: 源码驱动的回归验证
系统 SHALL 通过测试验证重构后的实现与源码行为保持一致，并避免旧功能回归。

#### Scenario: 运行回归验证
- **WHEN** 完成后端与前端重构
- **THEN** 应存在覆盖二维码登录协议、适配层能力、配置校验与异常路径的测试
- **AND** 相关测试、类型检查和必要校验应通过

## MODIFIED Requirements
### Requirement: 当前 weixin 集成实现
当前项目的 weixin 集成 SHALL 以 open-weixin 源码为唯一行为基准。任何已有实现只要与源码入口、字段命名、状态流转、超时语义或错误语义不一致，都必须以源码对齐后的行为为准进行重构。

## REMOVED Requirements
### Requirement: 基于历史推断的兼容结论
**Reason**: 历史实现中存在多轮围绕现象修补的兼容逻辑，其中部分字段与状态来自排障推断，不适合作为长期协议依据。
**Migration**: 逐项核对 open-weixin 源码中的真实协议与运行时行为，将现有接口、前端展示和测试替换为源码驱动的实现与断言。
