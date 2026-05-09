- [x] “新增供应商”弹窗中不再显示“图标地址（可选）”
- [x] “新增供应商”弹窗中不再显示“默认模型（可选）”
- [x] “新增供应商”弹窗中不再显示“API URL（可选）”
- [x] “新增供应商”弹窗中不再显示“API Key（可选）”
- [x] “新增供应商”弹窗中不再显示“最大 Token 数（可选）”
- [x] “新增供应商”弹窗新增并保留“显示名称（可选）”和“基础 URL（可选）”
- [x] 选择任一预置供应商时，基础 URL 输入框自动填充为对应根地址并追加 `/v1`
- [x] 连续切换不同供应商时，基础 URL 输入框实时更新且不会重复追加 `/v1`
- [x] 提交新增供应商表单时，请求中的基础 URL 字段符合 `{supplier-root}/v1` 规范
- [x] 提交新增供应商表单时，请求中不包含已移除的 5 个字段
- [x] 单元测试覆盖字段移除、URL 自动填充与提交载荷规范化场景
- [x] 端到端测试覆盖打开弹窗、切换供应商、检查基础 URL、提交表单场景
- [x] 相关单元测试、端到端测试和前端诊断检查通过

## 运行结果

- RTL：`npm run test -- SettingsPage.test.tsx` 通过，覆盖字段裁剪、预置供应商切换、URL 规范化提交
- Playwright：`$env:OPENAWA_E2E_REUSE_SERVER='true'; $env:OPENAWA_E2E_BACKEND_PORT=18000; $env:OPENAWA_E2E_FRONTEND_PORT=15173; npx playwright test tests/e2e/settings-provider-modal.spec.ts --project=chromium` 通过
- TypeScript：`npx tsc --noEmit` 通过
- 诊断：已编辑前端文件均无新增诊断错误
