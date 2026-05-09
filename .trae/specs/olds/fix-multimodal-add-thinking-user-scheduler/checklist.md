# Checklist

## 多模态输入修复

- [ ] ChatMessage schema 包含 attachments 字段，AttachmentItem 含 type/data/mime_type/file_name
- [ ] 后端 `build_multimodal_message()` 正确构建 OpenAI content parts 格式（text + image_url/audio_url/video_url）
- [ ] 后端 `build_multimodal_message()` 正确构建 Anthropic content blocks 格式
- [ ] 后端 `build_multimodal_message()` 对不支持多模态的模型返回纯文本格式（降级安全）
- [ ] 前端 ChatInput 支持图片上传（jpg/png/gif/webp，≤20MB）
- [ ] 前端 ChatInput 支持音频上传（mp3/wav/ogg，≤30MB）
- [ ] 前端 ChatInput 支持视频上传（mp4，≤50MB）
- [ ] 前端附件预览栏正确展示缩略图，支持逐个删除
- [ ] 前端对非多模态模型阻止发送附件并给出明确提示
- [ ] 模型能力 API `GET /api/models/{provider}/{model}/capabilities` 正常返回
- [ ] 图片输入后模型返回正确的图片分析结果（非纯文本）
- [ ] Terminal 中无新增 500 错误

## 思考模式控制

- [ ] ChatMessage schema 包含 thinking_enabled 和 thinking_depth 字段
- [ ] OpenAI o 系列模型深度映射正确（0-1→low, 2-3→medium, 4-5→high）
- [ ] Anthropic 模型深度映射正确（深度×4000 → budget_tokens）
- [ ] DeepSeek R1 模型 thinking 参数正确（仅 enabled，无分档深度）
- [ ] GLM 模型 thinking 参数正确
- [ ] 非推理模型（如 gpt-4o）不传递 thinking 参数
- [ ] 前端思考开关 Toggle 正常切换，状态实时同步
- [ ] 深度滑块 0-5 正常拖动，数值实时显示
- [ ] 思考参数正确透传到请求 payload
- [ ] 发送中开关/滑块处于禁用态（loading）
- [ ] 不支持思考的模型显示禁用态开关 + tooltip 说明
- [ ] 开启思考后返回结果包含 reasoning_content
- [ ] 关闭思考后返回结果不含 reasoning_content（或为空）
- [ ] 错误状态有清晰的错误提示

## 定时任务优化

- [ ] ScheduledTask 模型含 is_daily/cron_expression/weekdays/daily_time 字段
- [ ] 数据库迁移脚本正确运行，现有数据不丢失
- [ ] 后端创建每日任务时生成正确的 cron 表达式
- [ ] 后端计算并返回 next_execution_at 时间戳
- [ ] 每日任务执行后自动重新排程（而非标记为 completed）
- [ ] "是否每日执行"复选框展开/收起动画流畅
- [ ] 时间选择器支持 24 小时制，精确到分钟
- [ ] 星期多选按钮（周一至周日）可独立切换，默认全选
- [ ] Cron 表达式预览实时更新
- [ ] 未选星期时提交被阻止并显示错误提示
- [ ] 任务卡片展示"下次执行时间"
- [ ] UI 风格与 OpenClaw 一致（扁平、深色卡片、圆角、过渡动效）
- [ ] 编辑已有每日任务时正确回填所有字段

## 用户中心

- [ ] User 模型含 avatar_url/nickname/email/phone/profile_data 字段
- [ ] LoginDevice 表结构正确，登录时自动记录
- [ ] 登出时将对应 jti 加入黑名单
- [ ] 修改密码 API 正确验证旧密码 + 新密码强度
- [ ] 头像上传 API 校验文件大小 ≤1MB、类型 jpg/png
- [ ] AI 用户画像 API 返回兴趣标签、使用时长、活跃时段
- [ ] 远程登出 API 将指定设备 jti 加入黑名单
- [ ] 右下角悬浮用户区域固定定位，含头像 + 用户名 + 退出按钮
- [ ] 点击悬浮区域跳转至 /user
- [ ] /user 页面含 JWT 鉴权
- [ ] 用户中心 AI 画像模块展示标签云、使用时长、活跃时段
- [ ] 密码修改表单含强度指示器（弱/中/强）
- [ ] 头像上传含裁剪组件，实时预览裁剪效果
- [ ] 邮箱/手机绑定输入框正常（UI 占位可接受）
- [ ] 设备列表展示设备类型、IP、登录时间、当前设备标识
- [ ] 远程登出按钮功能正常
- [ ] 页面在 320px 宽度下布局正常（响应式）
- [ ] 页面在 1920px 宽度下布局正常
- [ ] 页面首次加载时间 < 1.5s
- [ ] 加载中/错误/空数据状态均有对应 UI

## 回归检查

- [ ] 现有单次定时任务创建/编辑/取消不受影响
- [ ] 现有聊天功能（纯文本）不受影响
- [ ] 现有登录/登出流程不受影响
- [ ] 现有 SSE 流式聊天不受影响
- [ ] TypeScript 类型检查零错误
- [ ] Python 语法解析零错误
- [ ] 后端测试全部通过
- [ ] 前端测试全部通过
