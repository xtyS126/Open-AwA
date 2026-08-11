# 旧页面淘汰和路由迁移矩阵

## 1. 迁移规则

- “淘汰”表示旧页面组件不再作为独立产品页面渲染。
- 迁移期旧 URL 只执行到规范路由的重定向，并尽可能保留实体 ID 或筛选状态。
- 重定向保留两个稳定版本；遥测确认外部深链使用量可接受后删除。
- 导航、站点地图、文档和测试从第一阶段起只引用规范路由。

## 2. 路由映射

| 当前路由/入口 | 目标规范路由 | 处理方式 |
|---|---|---|
| `/chat` | `/assistant` | 重命名；会话 ID 映射到 `/assistant/sessions/:id` |
| `/chat/:conversationId` | `/assistant/sessions/:conversationId` | 保留会话 ID 重定向 |
| `/workspace` | `/workbench/projects` | 页面能力并入工作台项目视图 |
| `/coding` | `/workbench/editor` | 编辑器成为工作台模式 |
| `/vibe-coding` | `/workbench/agents` | ACP/Vibe Coding 成为工作台模式 |
| `/workflows` | `/automations/flows` | 流程定义并入自动化 |
| `/scheduled-tasks` | `/automations/schedules` | 定时任务并入自动化计划 |
| `/subagents` | `/automations/executors` | 子智能体并入执行者管理 |
| `/discussions` | `/automations/runs` | 列表迁移到运行；不再保留讨论一级页 |
| `/discussions/:id` | `/automations/runs/:id/collaboration` | 讨论成为运行详情 Tab |
| `/skills` | `/library/capabilities?type=skill&view=installed` | 迁移到能力资源 |
| `/skills/market` | `/library/capabilities?type=skill&view=discover` | 删除独立市场页 |
| `/plugins` | `/library/capabilities?type=plugin&view=installed` | 删除中间重定向层 |
| `/plugins/manage` | `/library/capabilities?type=plugin&view=installed` | 迁移到能力资源 |
| `/plugins/config/:pluginId` | `/library/capabilities/plugin/:pluginId/config` | 资源详情内配置 Tab |
| 独立插件市场入口 | `/library/capabilities?type=plugin&view=discover` | 删除独立页面和重复样式层 |
| `/roles` | `/library/personas?view=installed` | 迁移到角色资源 |
| `/role-market` | `/library/personas?view=discover` | 删除独立市场页 |
| `/memory` | `/library/knowledge?view=long-term` | 迁移到知识资源 |
| `/experience` | `/library/knowledge?view=experience` | 删除独立经验页 |
| `/tts` | `/library/voices` | 迁移到声音资源 |
| `/dashboard` | `/activity/overview` | 并入动态概览 |
| `/inbox` | `/activity/inbox` | 并入动态收件箱 |
| `/billing` | `/activity/usage` | 用量与报表迁移；预算配置进入设置 |
| `/im` | `/settings/connections?type=messaging` | 从主导航移除，归入连接配置 |
| `/user` | `/account` | 账户规范入口 |
| `/user-profile` | `/account?section=profile` | 删除重复画像页面 |
| `/pets` | `/settings/appearance?section=companion` | 从资源/智能体导航移除 |
| `/settings` | `/settings/general` | 设置分区路由化 |

## 3. 组件收敛目标

| 当前组件 | 目标 |
|---|---|
| `Sidebar.tsx` 的三组手写菜单 | 替换为统一清单的 Web 投影器 |
| `MobileTabBar.tsx` 的独立常量 | 删除独立清单，投影五个领域 |
| Android `Destination.all/controlGroup/agentGroup/settingsGroup` | 由统一清单生成或映射，不再手写 |
| Android `PlaceholderScreen` 导航入口 | 全部删除；未就绪能力不展示 |
| `SkillMarketPage.tsx` | 内容迁入能力资源“发现”视图后删除 |
| `RoleMarketPage.tsx` | 内容迁入角色资源“发现”视图后删除 |
| `ExperiencePage.tsx` | 内容迁入知识资源“经验”视图后删除 |
| `UserProfilePage.tsx` | 与账户画像模块合并后删除 |
| 独立 Marketplace 页面样式 | 资源库共享 Catalog 组件后删除 |
| Electron 菜单中的页面知识 | 改为共享 `command_id`，只保留原生命令 |

## 4. 路由冲突处理

- 查询参数只表示筛选和视图，不表示另一个产品页面。
- 实体详情使用稳定 ID，不使用名称拼接路径。
- 旧路由重定向测试必须验证参数、实体 ID、返回路径和权限错误。
- 规范路由上线后，所有内部链接必须一次性切换，禁止继续产生旧 URL。

