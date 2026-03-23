# Tasks - 修复模型选择器失效问题

## 任务清单

- [x] Task 1: 在PricingManager中添加initialize_default_configurations方法
  - [x] SubTask 1.1: 创建DEFAULT_CONFIGURATIONS常量，定义5个常用模型配置
  - [x] SubTask 1.2: 实现initialize_default_configurations方法
  - [x] SubTask 1.3: 方法应检查重复记录，只在表为空时初始化
  - [x] SubTask 1.4: 添加日志记录初始化过程
  - [x] 验证: Python语法检查通过

- [x] Task 2: 在main.py中调用初始化方法
  - [x] SubTask 2.1: 在lifespan函数中添加initialize_default_configurations调用
  - [x] SubTask 2.2: 在initialize_default_pricing之后调用
  - [x] SubTask 2.3: 添加try-finally确保数据库连接关闭
  - [x] 验证: Python语法检查通过

- [x] Task 3: 增强ChatPage.tsx错误处理和用户体验
  - [x] SubTask 3.1: 添加error状态变量跟踪API错误
  - [x] SubTask 3.2: 添加retryCount状态实现自动重试（最多3次）
  - [x] SubTask 3.3: 在loadConfigurations中添加错误捕获和日志
  - [x] SubTask 3.4: 修改UI显示错误提示和重试按钮
  - [x] SubTask 3.5: 从localStorage恢复上次选择的模型
  - [x] SubTask 3.6: 添加"保存模型"按钮和相关状态
  - [x] 验证: TypeScript编译检查通过

- [x] Task 4: 优化ChatPage.css样式
  - [x] SubTask 4.1: 添加错误提示样式
  - [x] SubTask 4.2: 添加重试按钮样式
  - [x] SubTask 4.3: 优化模型选择器加载状态样式
  - [x] 验证: CSS语法正确

- [x] Task 5: 创建测试用例
  - [x] SubTask 5.1: 创建后端单元测试（test_pricing_manager.py）
  - [x] SubTask 5.2: 测试initialize_default_configurations方法
  - [x] SubTask 5.3: 测试重复初始化不会创建重复记录
  - [x] SubTask 5.4: 创建前端单元测试（ChatPage.test.tsx）
  - [x] SubTask 5.5: 测试模型加载和选择逻辑
  - [x] SubTask 5.6: 测试错误处理和重试机制
  - [x] ??: All tests passed (backend pytest + frontend vitest)

## Task Dependencies

- [Task 2] 依赖 [Task 1]
- [Task 3] 依赖 [Task 1] 和 [Task 2]
- [Task 4] 依赖 [Task 3]
- [Task 5] 依赖 [Task 1]、[Task 2]、[Task 3]

## 预期交付物

1. **后端修复**:
   - 修改 `backend/billing/pricing_manager.py`
   - 修改 `backend/main.py`

2. **前端增强**:
   - 修改 `frontend/src/pages/ChatPage.tsx`
   - 修改 `frontend/src/pages/ChatPage.css`

3. **测试**:
   - `backend/tests/test_pricing_manager.py`
   - `frontend/src/__tests__/ChatPage.test.tsx`

## 成功标准

- 模型选择器可正常展开、选中、切换模型
- 保存后刷新页面保持上次选择
- 无控制台报错
- 后端测试覆盖率 > 80%
- 前端测试覆盖主要交互逻辑
