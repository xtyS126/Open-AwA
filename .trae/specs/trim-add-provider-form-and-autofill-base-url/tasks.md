# Tasks

- [x] Task 1: 梳理新增供应商弹窗的当前字段、状态流和提交载荷
  - [x] SubTask 1.1: 确认“新增供应商”弹窗中 5 个待移除字段的渲染位置
  - [x] SubTask 1.2: 确认基础 URL 输入框当前值来源、供应商切换逻辑与提交字段映射
  - [x] SubTask 1.3: 确认预置供应商到根地址的映射来源，复用现有能力或补充最小映射表

- [x] Task 2: 精简新增供应商弹窗并实现基础 URL 自动填充
  - [x] SubTask 2.1: 移除图标地址、默认模型、API URL、API Key、最大 Token 数 5 个表单元素
  - [x] SubTask 2.2: 在选择预置供应商时自动填充基础 URL 为 `https://{supplier-domain}/v1`
  - [x] SubTask 2.3: 保证切换不同供应商时基础 URL 实时更新，且不会重复追加 `/v1`
  - [x] SubTask 2.4: 保证提交时发送给后台的基础 URL 字段值符合规范，且不携带已移除字段
  - [x] 验证: 手动结合 RTL / Playwright 检查弹窗字段与基础 URL 联动行为

- [x] Task 3: 补充自动化测试覆盖关键场景
  - [x] SubTask 3.1: 为新增供应商弹窗补充单元测试，覆盖字段移除与基础 URL 自动更新
  - [x] SubTask 3.2: 为表单提交补充测试，验证后台接收到的基础 URL 为 `{supplier-root}/v1`
  - [x] SubTask 3.3: 增加端到端测试，覆盖打开弹窗、切换供应商、检查基础 URL、提交请求
  - [x] 验证: 相关单元测试与端到端测试已通过

- [x] Task 4: 做最终联调与回归检查
  - [x] SubTask 4.1: 检查新增供应商弹窗在无配置和已有配置场景下均可正常使用
  - [x] SubTask 4.2: 检查右侧供应商详情中的基础 URL 编辑流程未被本次改动破坏
  - [x] SubTask 4.3: 运行前端类型检查与必要的诊断检查

## 运行结果

- `npm run test -- SettingsPage.test.tsx`：通过，`1` 个测试文件、`2` 个测试用例全部通过
- `npx tsc --noEmit`：通过，无 TypeScript 错误
- `OPENAWA_E2E_REUSE_SERVER=true OPENAWA_E2E_BACKEND_PORT=18000 OPENAWA_E2E_FRONTEND_PORT=15173 npx playwright test tests/e2e/settings-provider-modal.spec.ts --project=chromium`：通过，`1` 个 E2E 用例通过
- 诊断检查：`SettingsPage.tsx`、`SettingsPage.module.css`、`SettingsPage.test.tsx`、`settings-provider-modal.spec.ts` 均无新增诊断错误

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 依赖 Task 2 和 Task 3
