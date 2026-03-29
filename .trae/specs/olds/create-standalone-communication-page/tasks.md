# Tasks
- [x] Task 1: 梳理通讯配置从设置页拆分的边界
  - [x] SubTask 1.1: 确认现有通讯配置依赖的状态与服务调用
  - [x] SubTask 1.2: 明确需要保留与需要移除的设置页内容
  - [x] SubTask 1.3: 明确新路由与导航行为

- [x] Task 2: 新建独立通讯页面并迁移功能
  - [x] SubTask 2.1: 新增独立页面组件承载微信 Clawbot 配置
  - [x] SubTask 2.2: 迁移表单、保存、校验、健康检查交互
  - [x] SubTask 2.3: 从 SettingsPage 移除通讯配置区块

- [x] Task 3: 调整路由与侧边栏入口
  - [x] SubTask 3.1: 在 App 路由注册独立通讯页面路径
  - [x] SubTask 3.2: 将 Sidebar 的通讯入口切换为独立路径
  - [x] SubTask 3.3: 处理旧查询参数入口的兼容策略

- [x] Task 4: 更新测试并回归验证
  - [x] SubTask 4.1: 调整受影响的 SettingsPage 相关测试
  - [x] SubTask 4.2: 新增或更新独立通讯页面测试
  - [x] SubTask 4.3: 执行前端测试并验证无回归

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 2 and Task 3
