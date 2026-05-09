# Tasks

## 阶段一：多模态输入修复

- [x] Task 1: 后端 ChatMessage Schema 扩展 + 多模态内容构建
  - [x] 1.1 `api/schemas.py` ChatMessage 新增 `attachments: Optional[List[AttachmentItem]]` 字段，AttachmentItem 含 `type`（image/audio/video）、`data`（base64）、`mime_type`、`file_name`
  - [x] 1.2 `core/model_service.py` 新增 `build_multimodal_message()` 函数：根据 provider 将 text + attachments 构建为 OpenAI content parts 或 Anthropic content blocks
  - [x] 1.3 `core/agent.py` process_stream/process 方法在构建 LLM 调用前调用 `build_multimodal_message()`，传递 attachments 给底层 API
  - [x] 1.4 `core/executor.py` _build_messages_with_history 支持多模态 content 数组格式
  - [x] 1.5 `core/litellm_adapter.py` 支持传递 `thinking_params` 参数

- [ ] Task 2: 前端附件上传与多模态预览
  - [ ] 2.1 `ChatInput.tsx` 新增文件上传按钮（图片/音频/视频），支持拖拽上传
  - [ ] 2.2 文件校验：图片 ≤20MB（jpg/png/gif/webp），音频 ≤30MB（mp3/wav/ogg），视频 ≤50MB（mp4）
  - [ ] 2.3 附件预览栏：缩略图展示，支持删除单个附件
  - [ ] 2.4 前端读取文件为 base64，构建 attachments 数组
  - [ ] 2.5 发送消息时校验模型能力（从 `model_capabilities.json` 读取 `supports_vision` 等），非多模态模型阻止发送并提示

- [ ] Task 3: 模型能力获取 API
  - [ ] 3.1 `api/routes/models.py` 新增 `GET /api/models/{provider}/{model}/capabilities` 端点，从 `model_capabilities.json` 读取并返回
  - [ ] 3.2 前端 `api.ts` 新增 `modelAPI.getCapabilities()` 方法

---

## 阶段二：思考模式控制

- [x] Task 4: 后端思考参数映射与传递
  - [x] 4.1 `api/schemas.py` ChatMessage 新增 `thinking_enabled: Optional[bool]`、`thinking_depth: Optional[int]`（0-5）
  - [x] 4.2 `core/model_service.py` 新增 `build_thinking_params(provider, model, thinking_depth) -> dict`
  - [x] 4.3 `core/agent.py` _build_thinking_context 在构建 LLM 请求时注入 `thinking_params`；executor/litellm_adapter 全部透传

- [ ] Task 5: 前端思考模式 UI 组件
  - [ ] 5.1 `ChatPage.tsx` header 控件区新增 `ThinkingToggle` 组件（开关 + 深度滑块 0-5）
  - [ ] 5.2 组件状态通过 `chatStore` 管理：`thinkingEnabled`、`thinkingDepth`
  - [ ] 5.3 发送消息时将思考参数加入请求体
  - [ ] 5.4 loading 状态：发送中禁用开关/滑块
  - [ ] 5.5 错误提示：若模型不支持思考模式，开关显示禁用态 + tooltip 说明

---

## 阶段三：定时任务优化

- [x] Task 6: 后端 ScheduledTask 模型扩展 + Cron 调度
  - [x] 6.1 `db/models.py` ScheduledTask 表新增 `is_daily`、`cron_expression`、`weekdays`、`daily_time` 字段
  - [x] 6.2 `api/schemas.py` ScheduledTaskCreate/Update/Response 新增对应字段 + `next_execution_at`
  - [x] 6.3 `api/routes/scheduled_tasks.py` 创建/更新时生成 cron 表达式并计算 `next_execution_at`
  - [x] 6.4 `core/scheduled_task_manager.py` 支持 cron 调度，任务执行后重新排程
  - [x] 6.5 数据库迁移 _migrate_scheduled_task_daily_columns

- [ ] Task 7: 前端定时任务表单优化
  - [ ] 7.1 "是否每日执行"复选框，开启后展开每日执行配置区
  - [ ] 7.2 时间选择器（24 小时制，精确到分钟，`<input type="time">`）
  - [ ] 7.3 多选星期组件：7 个切换按钮（周一至周日），默认全选
  - [ ] 7.4 Cron 表达式预览：实时展示生成的 cron 表达式（只读）
  - [ ] 7.5 Cron 合法性校验：未选星期时提示"请至少选择一天"
  - [ ] 7.6 提交后解析后端返回的 `next_execution_at`，在任务卡片上展示"下次执行: ..."
  - [ ] 7.7 CSS 参考 OpenClaw 风格：扁平设计、深色背景卡片、圆角、流畅过渡动效

---

## 阶段四：用户中心

- [x] Task 8: 后端 User 模型与 API 扩展
  - [x] 8.1 `db/models.py` User 表新增 `avatar_url`、`nickname`、`email`、`phone`、`profile_data`（JSON）字段
  - [x] 8.2 新建 `LoginDevice` 表
  - [x] 8.3 `api/routes/auth.py` 登录成功时创建 LoginDevice 记录；`/logout` 时标记设备离线 + jti 黑名单
  - [x] 8.4 `api/routes/auth.py` 新增 `PUT /auth/me/password`（修改密码，含旧密码验证 + 强度校验）
  - [x] 8.5 新建 `api/routes/user.py`：`GET /user/profile`、`PUT /user/profile`、`POST /user/avatar`、`GET /user/devices`、`POST /user/devices/{id}/revoke`
  - [x] 8.6 AI 用户画像生成：从 BehaviorLog 生成兴趣标签、使用时长、活跃时段

- [ ] Task 9: 前端悬浮用户区域
  - [ ] 9.1 `shared/components/UserFloatingArea.tsx`：右下角固定定位，含头像圆圈、用户名、退出按钮
  - [ ] 9.2 点击头像/用户名跳转至 `/user`
  - [ ] 9.3 集成到 `App.tsx` 认证后布局中

- [ ] Task 10: 前端用户中心页面
  - [ ] 10.1 新建 `features/user/UserCenterPage.tsx`，路由注册 `/user`
  - [ ] 10.2 页面布局：左侧导航（画像/安全/设备），右侧内容区
  - [ ] 10.3 AI 画像模块：展示兴趣标签（彩色标签云）、使用时长统计、活跃时段图表
  - [ ] 10.4 密码修改表单：旧密码、新密码、确认新密码，实时强度指示器（弱/中/强），含后端校验
  - [ ] 10.5 头像上传模块：文件选择器（≤1MB jpg/png），裁剪组件（react-easy-crop 或自建），实时预览
  - [ ] 10.6 邮箱/手机绑定：输入框 + 发送验证码按钮（可先做 UI 占位，后续对接真实发送服务）
  - [ ] 10.7 设备管理列表：设备图标、IP 地址、登录时间、当前设备标识、"远程登出"按钮
  - [ ] 10.8 完全响应式：320-1920px，移动端导航折叠为顶部 tabs
  - [ ] 10.9 加载状态 + 错误提示 + 空数据占位

# Task Dependencies

- Task 3 依赖 Task 2（前端需要 capabilities API 做上传校验）
- Task 5 依赖 Task 4（前端思考 UI 依赖后端参数映射）
- Task 7 依赖 Task 6（前端表单依赖后端 cron 支持）
- Task 9 可与 Task 10 并行
- Task 8 是 Task 10 的前置依赖（后端 API 需先就绪）
- 阶段一、二、三、四之间无强依赖，可并行推进
