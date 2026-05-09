# Tasks

- [x] Task 1: 梳理并改造通用设置中的模型列表来源
  - [x] SubTask 1.1: 定位 `SettingsPage` 中通用设置模型下拉框的数据装载逻辑，移除初始化阶段基于本地计费配置直接拼装模型列表的行为
  - [x] SubTask 1.2: 明确通用设置模型选择器的触发条件，确保“刚创建时”不主动拉取远端模型列表
  - [x] SubTask 1.3: 调整数据源，使模型选项仅使用供应商远端接口返回的模型列表

- [x] Task 2: 为远端模型列表增加缓存与失效机制
  - [x] SubTask 2.1: 设计按供应商或配置维度缓存远端模型列表的前端状态结构
  - [x] SubTask 2.2: 接入缓存读取，避免短时间重复请求相同供应商的模型列表
  - [x] SubTask 2.3: 在基础 URL、API Key 或重新获取模型后清理对应缓存

- [x] Task 3: 调整通用设置 AI 参数配置区
  - [x] SubTask 3.1: 删除通用设置中“最大 Tokens”的输入 `div`
  - [x] SubTask 3.2: 在选择模型后联动读取该模型在计费配置中的最大 Tokens 信息
  - [x] SubTask 3.3: 在原区域下方新增模型详情展示，内容覆盖计费配置里的该模型全部相关信息，而不是供应商信息

- [x] Task 4: 处理映射、空态与异常反馈
  - [x] SubTask 4.1: 明确远端模型与本地计费配置模型的映射规则，处理“远端返回但本地无详情”与“本地存在但远端未返回”的情况
  - [x] SubTask 4.2: 为无可用远端模型、无模型详情、拉取失败、缓存失效后的重新拉取等状态提供清晰提示

- [x] Task 5: 补充验证与回归检查
  - [x] SubTask 5.1: 更新/新增前端单元测试，覆盖惰性加载、远端模型独占来源、最大 Tokens 区块移除、模型详情联动展示
  - [x] SubTask 5.2: 验证缓存命中与缓存失效行为符合预期
  - [x] SubTask 5.3: 运行前端类型检查、相关测试，并人工检查通用设置与 API 配置之间的联动是否无回归

## 运行结果

- `npm run test -- src/__tests__/features/settings/SettingsPage.test.tsx src/__tests__/features/settings/modelsApi.test.ts`：通过，`2` 个测试文件、`5` 个测试用例全部通过
- `npm run typecheck`：通过，无 TypeScript 错误
- 测试证据：`SettingsPage.test.tsx` 已覆盖“默认不自动拉取远端模型”“仅展示远端返回模型并忽略本地回退”“复用缓存避免重复请求”“移除最大 Tokens 输入并展示模型级详情”等关键路径
- 联动核验：`SettingsPage.tsx` 中 `loadGlobalModelOptions()` 仅在点击“加载远端模型/重新读取”后触发；`invalidateRemoteModelCache()` 在 API 配置的创建、保存、导入、删除与重新获取模型流程中都会执行，满足缓存失效与跨页联动要求

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 1 and Task 3
- Task 5 depends on Task 1, Task 2, Task 3, and Task 4
