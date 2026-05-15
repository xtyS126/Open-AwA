# 综合测试报告

**生成时间**：2026-05-16 00:50:38
**报告周期**：2026-05-16
**项目**：Open-AwA

---

## 📋 执行摘要

| 指标 | 值 |
|------|-----|
| 测试文件总数 | 121 |
| 后端测试文件 | 64 |
| 前端测试文件 | 39 |
| E2E 测试文件 | 15 |
| 技能测试文件 | 3 |
| 后端覆盖率 | 🔴 不足 (25.0%) |
| 前端覆盖率 | ⚠️ 数据不可用 |
| 近期新增测试 | 73 个文件 |

---

## 📊 各层级测试统计

### 2.1 后端测试 (pytest)

| 指标 | 值 |
|------|-----|
| 测试文件数 | 64 |
| 覆盖率 | █████░░░░░░░░░░░░░░░ 25.0% |

**后端测试模块分布**：

| 模块 | 测试文件数 |
|------|-----------|
| 插件系统 | 11 |
| 安全 | 7 |
| Agent 核心 | 6 |
| 记忆/经验 | 6 |
| 其他 | 5 |
| 计费系统 | 5 |
| 任务运行时 | 5 |
| API/路由 | 4 |
| 微信 | 4 |
| 基础设施 | 4 |
| 对话/Chat | 3 |
| 本地服务 | 2 |
| 用户 | 1 |
| 工作流 | 1 |

### 2.2 前端测试 (vitest)

| 指标 | 值 |
|------|-----|
| 测试文件数 | 39 |
| 覆盖率 | ░░░░░░░░░░░░░░░░░░░░ 数据不可用 |

**前端测试模块分布**：

| 模块 | 测试文件数 |
|------|-----------|
| 聊天 (Chat) | 7 |
| 页面/根组件 | 6 |
| 插件 (Plugins) | 6 |
| 计费 (Billing) | 3 |
| 经验 (Experiences) | 3 |
| 设置 (Settings) | 3 |
| 仪表盘 (Dashboard) | 2 |
| 技能 (Skills) | 2 |
| 共享 API | 2 |
| 记忆 (Memory) | 1 |
| 共享组件 | 1 |
| 共享 Store | 1 |
| 共享类型 | 1 |
| 共享工具 | 1 |

### 2.3 E2E 测试 (Playwright)

| 指标 | 值 |
|------|-----|
| 测试文件数 | 15 |
| - auth-flow.spec.ts | |
| - auth.ts | |
| - billing-budget.spec.ts | |
| - chat-conversations.spec.ts | |
| - chat-full-journey.spec.ts | |
| - compatibility-matrix.spec.ts | |
| - responsive-layout.spec.ts | |
| - visual-regression.spec.ts | |
| - electron-smoke.spec.ts | |
| - memory-experience.spec.ts | |
| - plugins-hot-update.spec.ts | |
| - plugins-lifecycle.spec.ts | |
| - settings-full-config.spec.ts | |
| - settings-provider-modal.spec.ts | |
| - wechat-auto-reply.spec.ts | |

### 2.4 技能测试

| 指标 | 值 |
|------|-----|
| 测试文件数 | 3 |
| - test_assertions.py | |
| - test_exception_handler.py | |
| - test_reporter.py | |

---

## 📦 测试资产清单

### 3.1 后端测试文件列表

<details>
<summary>展开查看全部 64 个后端测试文件</summary>

- `backend\tests\test_agent_capability_prompt.py`
- `backend\tests\test_agent_core.py`
- `backend\tests\test_api_route_regressions.py`
- `backend\tests\test_api_skills_weixin.py`
- `backend\tests\test_auth_dependencies_token_resolution.py`
- `backend\tests\test_auth_rate_limit_and_mcp_manager.py`
- `backend\tests\test_backend_protocol_features.py`
- `backend\tests\test_behavior_logger.py`
- `backend\tests\test_billing_calculator.py`
- `backend\tests\test_billing_uniqueness.py`
- `backend\tests\test_budget_manager.py`
- `backend\tests\test_chat_streaming_status.py`
- `backend\tests\test_code_review_fixes.py`
- `backend\tests\test_comprehension.py`
- `backend\tests\test_config_security.py`
- `backend\tests\test_conversation_recorder.py`
- `backend\tests\test_conversation_sessions_api.py`
- `backend\tests\test_db_get_db_logging.py`
- `backend\tests\test_db_models.py`
- `backend\tests\test_deepseek_tokenizer_utils.py`
- `backend\tests\test_executor_tool_calling.py`
- `backend\tests\test_experience_settings.py`
- `backend\tests\test_extension_protocol.py`
- `backend\tests\test_hot_update.py`
- `backend\tests\test_litellm_adapter.py`
- `backend\tests\test_local_search.py`
- `backend\tests\test_local_users.py`
- `backend\tests\test_logging_utils.py`
- `backend\tests\test_main_startup.py`
- `backend\tests\test_memory_tools.py`
- `backend\tests\test_memory_workflow_api.py`
- `backend\tests\test_memory_workflow_edge_cases.py`
- `backend\tests\test_memory_workflow_enhancements.py`
- `backend\tests\test_migrate_db_security.py`
- `backend\tests\test_planner.py`
- `backend\tests\test_plugin_cli.py`
- `backend\tests\test_plugin_context_and_deps.py`
- `backend\tests\test_plugin_event_bus.py`
- `backend\tests\test_plugin_lifecycle.py`
- `backend\tests\test_plugin_observability.py`
- `backend\tests\test_plugin_performance_baseline.py`
- `backend\tests\test_plugins_import_url_api.py`
- `backend\tests\test_pricing_manager.py`
- `backend\tests\test_provider_endpoint_resolution.py`
- `backend\tests\test_sandbox_backends.py`
- `backend\tests\test_sandbox_security.py`
- `backend\tests\test_scheduled_task_manager.py`
- `backend\tests\test_security_permission.py`
- `backend\tests\test_security_rbac.py`
- `backend\tests\test_settings_paths.py`
- `backend\tests\test_skill_executor_security.py`
- `backend\tests\test_task_runtime_api.py`
- `backend\tests\test_task_runtime_phase1.py`
- `backend\tests\test_task_runtime_phase2.py`
- `backend\tests\test_task_runtime_phase3.py`
- `backend\tests\test_task_runtime_phase4.py`
- `backend\tests\test_twitter_monitor_plugin.py`
- `backend\tests\test_user_preferences.py`
- `backend\tests\test_user_profile_chat_plugin.py`
- `backend\tests\test_vector_store_manager.py`
- `backend\tests\test_weixin_auto_reply.py`
- `backend\tests\test_weixin_auto_reply_coverage.py`
- `backend\tests\test_weixin_skill_adapter.py`
- `backend\tests\test_workflow_engine.py`

</details>

### 3.2 前端测试文件列表

<details>
<summary>展开查看全部 39 个前端测试文件</summary>

- `frontend\src\__tests__\App.test.tsx`
- `frontend\src\__tests__\AuthPage.test.tsx`
- `frontend\src\__tests__\features\billing\billing.test.ts`
- `frontend\src\__tests__\features\billing\billingApi.test.ts`
- `frontend\src\__tests__\features\billing\BillingPage.test.tsx`
- `frontend\src\__tests__\features\chat\assistantSegments.test.ts`
- `frontend\src\__tests__\features\chat\ChatPage.test.tsx`
- `frontend\src\__tests__\features\chat\CommunicationPage.test.tsx`
- `frontend\src\__tests__\features\chat\components\ReasoningContent.test.tsx`
- `frontend\src\__tests__\features\chat\components\SubagentExecutionContainer.test.tsx`
- `frontend\src\__tests__\features\chat\executionMeta.test.ts`
- `frontend\src\__tests__\features\chat\store\chatStore.test.ts`
- `frontend\src\__tests__\features\dashboard\dashboard.test.ts`
- `frontend\src\__tests__\features\dashboard\DashboardPage.test.tsx`
- `frontend\src\__tests__\features\experiences\ExperiencePage.test.tsx`
- `frontend\src\__tests__\features\experiences\experiencesApi.test.ts`
- `frontend\src\__tests__\features\experiences\fileExperiencesApi.test.ts`
- `frontend\src\__tests__\features\memory\MemoryPage.test.tsx`
- `frontend\src\__tests__\features\plugins\components\PluginConfigPage.test.tsx`
- `frontend\src\__tests__\features\plugins\components\PluginDebugPanel.test.tsx`
- `frontend\src\__tests__\features\plugins\hooks.test.ts`
- `frontend\src\__tests__\features\plugins\MarketplacePage.test.tsx`
- `frontend\src\__tests__\features\plugins\PluginDebugPanel.test.tsx`
- `frontend\src\__tests__\features\plugins\PluginsPage.test.tsx`
- `frontend\src\__tests__\features\settings\modelsApi.test.ts`
- `frontend\src\__tests__\features\settings\SettingsPage.test.tsx`
- `frontend\src\__tests__\features\settings\SettingsPageWeixin.test.tsx`
- `frontend\src\__tests__\features\skills\SkillModal.test.tsx`
- `frontend\src\__tests__\features\skills\SkillsPage.test.tsx`
- `frontend\src\__tests__\main.test.tsx`
- `frontend\src\__tests__\ScheduledTasksPage.test.tsx`
- `frontend\src\__tests__\setupTests.test.ts`
- `frontend\src\__tests__\shared\api\api.test.ts`
- `frontend\src\__tests__\shared\api\taskApiCsrfCompatibility.test.ts`
- `frontend\src\__tests__\shared\components\Sidebar\Sidebar.test.tsx`
- `frontend\src\__tests__\shared\store\authStore.test.ts`
- `frontend\src\__tests__\shared\types\api.test.ts`
- `frontend\src\__tests__\shared\utils\logger.test.ts`
- `frontend\src\__tests__\UserPage.test.tsx`

</details>

---

## 🆕 近期新增测试文件（30 天内）

共新增 **73** 个测试文件：

**后端新增**：
- `backend/tests/test_agent_capability_prompt.py`
- `backend/tests/test_agent_core.py`
- `backend/tests/test_billing_calculator.py`
- `backend/tests/test_billing_uniqueness.py`
- `backend/tests/test_budget_manager.py`
- `backend/tests/test_chat_streaming_status.py`
- `backend/tests/test_comprehension.py`
- `backend/tests/test_config_security.py`
- `backend/tests/test_conversation_sessions_api.py`
- `backend/tests/test_db_models.py`
- `backend/tests/test_deepseek_tokenizer_utils.py`
- `backend/tests/test_executor_tool_calling.py`
- `backend/tests/test_experience_settings.py`
- `backend/tests/test_local_search.py`
- `backend/tests/test_local_users.py`
- `backend/tests/test_memory_tools.py`
- `backend/tests/test_memory_workflow_api.py`
- `backend/tests/test_memory_workflow_edge_cases.py`
- `backend/tests/test_memory_workflow_enhancements.py`
- `backend/tests/test_planner.py`
- `backend/tests/test_plugin_context_and_deps.py`
- `backend/tests/test_plugin_event_bus.py`
- `backend/tests/test_plugins_import_url_api.py`
- `backend/tests/test_sandbox_backends.py`
- `backend/tests/test_scheduled_task_manager.py`
- `backend/tests/test_security_permission.py`
- `backend/tests/test_security_rbac.py`
- `backend/tests/test_task_runtime_api.py`
- `backend/tests/test_task_runtime_phase1.py`
- `backend/tests/test_task_runtime_phase2.py`
- `backend/tests/test_task_runtime_phase3.py`
- `backend/tests/test_task_runtime_phase4.py`
- `backend/tests/test_twitter_monitor_plugin.py`
- `backend/tests/test_user_preferences.py`
- `backend/tests/test_user_profile_chat_plugin.py`
- `backend/tests/test_vector_store_manager.py`
- `backend/tests/test_weixin_auto_reply_coverage.py`
- `backend/tests/test_workflow_engine.py`

**前端新增**：
- `frontend/src/__tests__/features/billing/BillingPage.test.tsx`
- `frontend/src/__tests__/features/billing/billing.test.ts`
- `frontend/src/__tests__/features/billing/billingApi.test.ts`
- `frontend/src/__tests__/features/chat/ChatPage.test.tsx`
- `frontend/src/__tests__/features/chat/CommunicationPage.test.tsx`
- `frontend/src/__tests__/features/chat/assistantSegments.test.ts`
- `frontend/src/__tests__/features/chat/components/ReasoningContent.test.tsx`
- `frontend/src/__tests__/features/chat/components/SubagentContainer.test.tsx`
- `frontend/src/__tests__/features/chat/components/SubagentExecutionContainer.test.tsx`
- `frontend/src/__tests__/features/chat/components/useSubagentManager.test.ts`
- `frontend/src/__tests__/features/chat/executionMeta.test.ts`
- `frontend/src/__tests__/features/chat/store/chatStore.test.ts`
- `frontend/src/__tests__/features/dashboard/DashboardPage.test.tsx`
- `frontend/src/__tests__/features/dashboard/dashboard.test.ts`
- `frontend/src/__tests__/features/experiences/ExperiencePage.test.tsx`
- `frontend/src/__tests__/features/experiences/experiencesApi.test.ts`
- `frontend/src/__tests__/features/experiences/fileExperiencesApi.test.ts`
- `frontend/src/__tests__/features/memory/MemoryPage.test.tsx`
- `frontend/src/__tests__/features/plugins/MarketplacePage.test.tsx`
- `frontend/src/__tests__/features/plugins/PluginDebugPanel.test.tsx`
- `frontend/src/__tests__/features/plugins/PluginsPage.test.tsx`
- `frontend/src/__tests__/features/plugins/components/PluginConfigPage.test.tsx`
- `frontend/src/__tests__/features/plugins/components/PluginDebugPanel.test.tsx`
- `frontend/src/__tests__/features/plugins/hooks.test.ts`
- `frontend/src/__tests__/features/settings/SettingsPage.test.tsx`
- `frontend/src/__tests__/features/settings/SettingsPageWeixin.test.tsx`
- `frontend/src/__tests__/features/settings/modelsApi.test.ts`
- `frontend/src/__tests__/features/skills/SkillModal.test.tsx`
- `frontend/src/__tests__/features/skills/SkillsPage.test.tsx`
- `frontend/src/__tests__/shared/api/api.test.ts`
- `frontend/src/__tests__/shared/api/taskApiCsrfCompatibility.test.ts`
- `frontend/src/__tests__/shared/components/Sidebar/Sidebar.test.tsx`
- `frontend/src/__tests__/shared/store/authStore.test.ts`
- `frontend/src/__tests__/shared/types/api.test.ts`
- `frontend/src/__tests__/shared/utils/logger.test.ts`

---

## 📈 覆盖率详情

### 5.1 后端覆盖率

- **语句覆盖率**：25.0%
- **覆盖报告路径**：`backend/reports/backend-coverage/index.html`

### 5.2 前端覆盖率

> ⚠️ 覆盖率数据不可用。请运行 `npx vitest run --coverage` 生成覆盖率报告。

---

## ✅ 代码质量检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 后端 mypy 零错误 | ⬜ 待检查 | 运行 `mypy backend/ --ignore-missing-imports` |
| 后端 bandit 安全扫描 | ⬜ 待检查 | 运行 `bandit -r backend/` |
| 前端 TypeScript 零错误 | ⬜ 待检查 | 运行 `npx tsc --noEmit` |
| 前端 ESLint 零错误 | ⬜ 待检查 | 运行 `npx eslint src/` |
| 前端构建成功 | ⬜ 待检查 | 运行 `npm run build` |
| 安全依赖审计 | ⬜ 待检查 | 运行 `pip-audit` / `npm audit` |
| 覆盖率阈值检查 | ✅ 通过 | 满足最低覆盖率要求 |

---

## ⚠️ 遗留问题

- 前端覆盖率报告未生成，无法评估覆盖率水平

---

## 📝 报告说明

- 本报告由 `scripts/generate_test_report.py` 自动生成
- 报告生成时间：2026-05-16 00:50:38
- 覆盖率数据来源：
  - 后端：`pytest --cov` 的 HTML 报告（coverage.py）
  - 前端：`vitest --coverage` 的 HTML/JSON 报告（v8/istanbul）
- 测试文件统计：基于文件系统扫描（`test_*.py` 和 `*.test.*`）
- 新增文件检测：使用 `git log --diff-filter=A --since=30.days`
