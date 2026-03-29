# 经验页文件化改造 Spec

## Why
当前经验页访问时报 `AxiosError: Request failed with status code 500`，说明现有经验数据读取链路不可用。用户希望同时简化经验管理方式：不再依赖现有数据库经验页，而是直接展示并编辑 `memory_skill` 文件夹中的 Markdown 文件，并让 `experience-extractor` 将提取结果保存到该目录下。

## What Changes
- 将经验页的数据源改为 `memory_skill` 文件夹内的 Markdown 文件
- 新增后端文件型经验接口，用于列出、读取、保存 Markdown 文件
- 将经验页改造成“文件列表 + 编辑区”的可编辑页面
- 修改 `experience-extractor`，使其将提取经验保存到 `memory_skill` 目录
- 保留现有数据库经验相关代码，但本次页面不再依赖它
- **BREAKING** 经验页前端接口调用从原有经验接口切换为新的文件接口

## Impact
- Affected specs: 经验管理、经验提取、经验页面展示
- Affected code:
  - `backend/api/routes/experiences.py`
  - `backend/skills/experience_extractor.py`
  - `backend/main.py`
  - `frontend/src/pages/ExperiencePage.tsx`
  - `frontend/src/services/*`
  - `memory_skill/`

## ADDED Requirements

### Requirement: 文件型经验列表
系统 SHALL 提供读取 `memory_skill` 目录下 Markdown 文件列表的能力，并返回页面可展示的基础信息。

#### Scenario: 成功列出经验文件
- **WHEN** 用户进入经验页
- **THEN** 后端返回 `memory_skill` 目录内所有 Markdown 文件的列表
- **AND** 每条记录至少包含文件名、标题、更新时间、摘要或首段内容

#### Scenario: 目录不存在
- **WHEN** 系统首次访问经验目录且目录尚未创建
- **THEN** 系统自动创建目录
- **AND** 返回空列表而不是 500 错误

### Requirement: 文件型经验详情与保存
系统 SHALL 支持读取单个 Markdown 文件全文，并支持编辑后保存回原文件。

#### Scenario: 查看经验详情
- **WHEN** 用户点击某条经验文件
- **THEN** 页面加载该 Markdown 文件的完整内容
- **AND** 用户可以进入编辑态

#### Scenario: 保存编辑内容
- **WHEN** 用户在经验页修改 Markdown 内容并保存
- **THEN** 后端将更新后的内容写回目标文件
- **AND** 接口返回最新更新时间与保存结果

### Requirement: experience-extractor 写入 memory_skill
系统 SHALL 让 `experience-extractor` 将提取出的经验内容保存为 Markdown 文件到 `memory_skill` 目录下。

#### Scenario: 提取成功并写入文件
- **WHEN** `experience-extractor` 成功生成经验内容
- **THEN** 系统在 `memory_skill` 目录下创建新的 Markdown 文件
- **AND** 返回生成的文件名或保存路径信息

### Requirement: 文件访问安全
系统 SHALL 限制经验文件操作只能发生在指定目录内，避免路径穿越风险。

#### Scenario: 非法文件名请求
- **WHEN** 请求中的文件名包含路径穿越片段或非法路径
- **THEN** 后端拒绝请求并返回明确错误
- **AND** 不访问目录外文件

### Requirement: 经验页路由可达性
系统 SHALL 在前端路由表中为 `/experience` 注册经验页面组件，确保用户从侧边栏进入时主内容区域可见。

#### Scenario: 侧边栏进入经验页
- **WHEN** 用户点击侧边栏“经验”并跳转到 `/experience`
- **THEN** 路由命中经验页面组件并在 `main` 区域渲染内容
- **AND** 页面继续使用文件型经验接口加载列表

## MODIFIED Requirements

### Requirement: 经验页展示方式
经验页不再以数据库经验记录为主视图，而改为展示 `memory_skill` 目录下的 Markdown 文件列表及编辑界面。

#### Scenario: 页面加载成功
- **WHEN** 用户打开经验页
- **THEN** 页面优先展示文件列表
- **AND** 用户可在同页查看、编辑、保存 Markdown 内容
- **AND** 页面不因旧数据库经验接口异常而白屏或报 500

### Requirement: 经验接口错误处理
经验相关后端接口必须在目录为空、文件不存在、内容格式异常等情况下返回可处理错误，而不是未捕获异常。

#### Scenario: 文件不存在
- **WHEN** 前端请求的经验文件不存在
- **THEN** 后端返回 404 或明确业务错误
- **AND** 前端显示可理解的提示信息

## REMOVED Requirements

### Requirement: 经验页依赖数据库经验列表
**Reason**: 用户明确要求经验页改为展示 `memory_skill` 中的 Markdown 文件，并以文件编辑为核心交互。
**Migration**: 旧数据库经验数据暂不删除；本次仅停止经验页对其依赖，后续如有需要再提供迁移脚本或导入功能。
