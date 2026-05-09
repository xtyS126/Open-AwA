# 新增供应商表单精简与基础 URL 自动填充 Spec

## Why
当前“新增供应商”弹窗暴露了过多非必要字段，增加了配置复杂度，也容易让用户填入不规范的 URL。需要收敛表单输入项，并在用户选择预置供应商时自动生成规范化的基础 URL，降低配置成本与后端接收脏数据的风险。

## What Changes
- 移除“新增供应商”弹窗中的 5 个表单元素：图标地址、默认模型、API URL、API Key、最大 Token 数
- 保留并继续使用基础 URL 输入能力，但在供应商选择变化时自动填充为对应根地址并追加 `/v1`
- 约束前端提交的基础 URL 字段格式为 `https://{supplier-domain}/v1`
- 为表单裁剪、URL 自动更新、提交载荷规范化补充单元测试与端到端测试

## Impact
- Affected specs: 设置页 API 配置、供应商创建流程、前端表单校验、测试覆盖
- Affected code: `frontend/src/features/settings/SettingsPage.tsx`、相关样式与测试文件、供应商 API 调用封装、可能涉及创建供应商请求的后端测试桩

## ADDED Requirements
### Requirement: 新增供应商表单最小化
系统 SHALL 在“新增供应商”弹窗中仅保留本次创建所必需的字段，不展示已被移除的 5 个元素。

#### Scenario: 打开新增供应商弹窗
- **WHEN** 用户打开“新增供应商”弹窗
- **THEN** 页面不显示“图标地址（可选）”“默认模型（可选）”“API URL（可选）”“API Key（可选）”“最大 Token 数（可选）”
- **THEN** 用户仍可完成供应商选择、显示名称编辑以及基础 URL 相关操作

### Requirement: 基础 URL 自动填充
系统 SHALL 在用户选择预置供应商时，自动将基础 URL 输入框填充为该供应商的根地址并追加 `/v1` 后缀。

#### Scenario: 切换预置供应商
- **WHEN** 用户在“供应商标识”下拉框中切换为任一预置供应商
- **THEN** 基础 URL 输入框实时更新
- **THEN** 更新后的值符合 `https://{supplier-domain}/v1` 格式

#### Scenario: 重复切换不同供应商
- **WHEN** 用户连续切换多个不同的预置供应商
- **THEN** 基础 URL 输入框每次都覆盖为当前选中供应商对应的地址
- **THEN** 最终值不重复追加 `/v1`

### Requirement: 创建请求 URL 规范化
系统 SHALL 在提交新增供应商表单时，向后台发送规范化后的基础 URL 字段值。

#### Scenario: 提交新增供应商表单
- **WHEN** 用户提交新增供应商表单
- **THEN** 前端发送给后台的基础 URL 字段值符合 `https://{supplier-root}/v1` 规范
- **THEN** 不发送已从 UI 移除且当前流程不再需要的字段

## MODIFIED Requirements
### Requirement: 新增供应商弹窗字段行为
新增供应商弹窗的字段集合调整为以“供应商选择 + 必需配置”为核心。对于预置供应商，基础 URL 由前端按供应商映射自动生成并展示给用户；用户切换供应商时，该值需同步更新，且不得出现多余路径或重复 `/v1`。

## REMOVED Requirements
### Requirement: 新增供应商弹窗允许直接录入扩展配置字段
**Reason**: 这些字段在新增供应商的首屏流程中非必需，保留会增加认知负担并提高填错风险。
**Migration**: 已移除字段如仍需编辑，应在供应商创建完成后进入右侧供应商详情区域进行补充配置。
