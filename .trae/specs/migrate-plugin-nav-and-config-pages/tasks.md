# Tasks
- [x] Task 1: 重构插件侧边栏信息架构与嵌套路由
  - [x] SubTask 1.1: 将 `插件` 入口改为可展开分支并新增子项 `插件管理`、`插件配置`
  - [x] SubTask 1.2: 配置前端嵌套路由 `/plugins/manage` 与 `/plugins/config/:pluginId`
  - [x] SubTask 1.3: 保证旧插件入口跳转兼容到新路由

- [x] Task 2: 实现插件管理页面 `/plugins/manage`
  - [x] SubTask 2.1: 构建插件列表视图（名称、版本、作者、状态、简介缩略）
  - [x] SubTask 2.2: 实现关键词搜索、批量选择与批量删除
  - [x] SubTask 2.3: 实现导入能力（本地上传 ZIP、远程 URL）与简介查看
  - [x] SubTask 2.4: 为导入/删除/异常场景接入 Toast 反馈

- [x] Task 3: 实现插件配置页面 `/plugins/config/:pluginId`
  - [x] SubTask 3.1: 根据 `schema.json` 动态生成表单
  - [x] SubTask 3.2: 支持 `input`、`select`、`switch`、`code-editor`、`file-picker` 五类控件
  - [x] SubTask 3.3: 增加实时校验与错误展示，禁止非法提交
  - [x] SubTask 3.4: 保存配置到 `${pluginId}/config.json` 并触发页面内实时生效

- [x] Task 4: 实现配置辅助工具链
  - [x] SubTask 4.1: 增加 `重置默认`、`导出配置`、`导入配置` 三个按钮
  - [x] SubTask 4.2: 三项操作统一增加二次确认弹窗
  - [x] SubTask 4.3: 完成导入配置覆盖逻辑与回滚提示

- [x] Task 5: 抽象插件异步 hooks
  - [x] SubTask 5.1: 封装列表查询、导入、删除、详情、配置读写 hooks
  - [x] SubTask 5.2: 每个 hook 提供 `loading`、`error`、`retry` 状态
  - [x] SubTask 5.3: 页面改造为仅消费 hooks，不直接写异步副作用

- [x] Task 6: 测试与性能验收
  - [x] SubTask 6.1: 增加导入解析单元测试
  - [x] SubTask 6.2: 增加配置表单渲染单元测试
  - [x] SubTask 6.3: 增加配置持久化单元测试
  - [x] SubTask 6.4: 覆盖率达到并验证不低于 80%
  - [x] SubTask 6.5: 验证导入耗时、首渲染耗时与内存快照增长指标

- [x] Task 7: 文档交付
  - [x] SubTask 7.1: 更新 README 目录结构与环境变量说明
  - [x] SubTask 7.2: 增补插件包格式规范（`index.js`、`schema.json`、`README.md`）
  - [x] SubTask 7.3: 增补本地调试步骤与常见排错

- [x] Task 8: 修复路由结构未满足“嵌套路由”验收项
  - [x] SubTask 8.1: 将 `App.tsx` 中 `/plugins/manage` 与 `/plugins/config/:pluginId` 重构为同一父路由下的嵌套路由
  - [x] SubTask 8.2: 保持现有独立访问能力与旧入口 `/plugins` 重定向兼容
  - 失败说明：当前实现为平铺路由（`/plugins/manage`、`/plugins/config/:pluginId` 直接定义在顶层），不满足“采用嵌套结构”的验收描述

- [x] Task 9: 修复插件异步流程未统一通过 hooks 封装
  - [x] SubTask 9.1: 为配置页与权限相关异步流程补充 hooks（含 schema 拉取、保存、重置、导出、权限刷新等）
  - [x] SubTask 9.2: 统一在页面层仅消费 hooks 暴露的 `loading`、`error`、`retry`
  - [x] SubTask 9.3: 移除页面中直接调用 `pluginsAPI` 的异步副作用
  - 失败说明：`PluginConfigPage` 与部分插件操作仍在页面组件中直接调用 API，未完全满足“插件异步操作均通过 hooks 封装”

- [x] Task 10: 修复相关测试覆盖率未达到 80%
  - [x] SubTask 10.1: 为 `features/plugins/hooks.ts` 增加单元测试，覆盖列表、导入、删除、详情、配置保存与重试分支
  - [x] SubTask 10.2: 为 `MarketplacePage.tsx` 或其替代路径补齐测试，避免插件模块覆盖率被未测文件拉低
  - [x] SubTask 10.3: 执行 `npm run test:coverage` 并输出插件相关模块覆盖率证据
  - 失败说明：本次覆盖率报告中插件模块聚合覆盖率约为 61.48%，未达到“相关测试覆盖率 >= 80%”目标

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 3
- Task 5 depends on Task 2 and Task 3
- Task 6 depends on Task 2, Task 3, Task 4, and Task 5
- Task 7 depends on Task 2, Task 3, and Task 6
- Task 8 depends on Task 1
- Task 9 depends on Task 5
- Task 10 depends on Task 6 and Task 9
