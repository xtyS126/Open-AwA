# Tasks

## Phase 1: 后端核心消息处理管道

- [x] Task 1: 重构 WeixinSkillAdapter 为模块化消息处理引擎
  - [x] 1.1 创建 `backend/skills/weixin/` 目录结构
  - [x] 1.2 将现有 `weixin_skill_adapter.py` 拆分为多个模块
  - [x] 1.3 创建 `messaging/inbound.py` - 入站消息解析
  - [x] 1.4 创建 `messaging/outbound.py` - 出站消息发送
  - [x] 1.5 创建 `messaging/process.py` - 消息处理主流程
  - [x] 1.6 保持原有接口兼容性

- [x] Task 2: 实现长轮询监控循环
  - [x] 2.1 创建 `monitor/loop.py` - 监控主循环
  - [x] 2.2 实现 get_updates 游标持久化
  - [x] 2.3 实现错误恢复策略（指数退避、熔断）
  - [x] 2.4 实现会话过期检测与暂停保护
  - [x] 2.5 添加监控启动/停止接口

- [x] Task 3: 实现斜杠指令系统
  - [x] 3.1 创建 `messaging/commands.py` - 指令处理器
  - [x] 3.2 实现 `/echo` 指令 - 通道延迟测试
  - [x] 3.3 实现 `/toggle-debug` 指令 - 调试模式切换
  - [x] 3.4 实现 `/task` 指令 - 异步任务管理
  - [x] 3.5 实现指令权限检查

- [x] Task 4: 实现消息格式转换
  - [x] 4.1 创建 `messaging/format.py` - 格式转换工具
  - [x] 4.2 实现 Markdown 转纯文本
  - [x] 4.3 实现代码块格式处理
  - [x] 4.4 实现链接、表格、列表转换
  - [x] 4.5 实现消息分块（超过4000字符自动分割）

## Phase 2: 媒体处理能力

- [x] Task 5: 实现 CDN 上传模块
  - [x] 5.1 创建 `cdn/upload.py` - CDN上传逻辑
  - [x] 5.2 实现 AES-128-ECB 加密
  - [x] 5.3 实现 getUploadUrl 接口调用
  - [x] 5.4 实现文件上传与进度追踪
  - [x] 5.5 实现上传失败重试

- [x] Task 6: 实现媒体下载与解密
  - [x] 6.1 创建 `cdn/download.py` - 媒体下载逻辑
  - [x] 6.2 实现 CDN URL 构建
  - [x] 6.3 实现 AES 解密
  - [x] 6.4 实现下载缓存管理

- [x] Task 7: 实现语音转码
  - [x] 7.1 创建 `media/transcode.py` - 语音转码逻辑
  - [x] 7.2 集成 SILK 解码器（silk-wasm 或 ffmpeg）
  - [x] 7.3 实现语音转文字（可选集成ASR服务）
  - [x] 7.4 实现转码失败降级处理

## Phase 3: 异步任务系统

- [x] Task 8: 实现异步任务管理
  - [x] 8.1 创建 `tasks/manager.py` - 任务管理器
  - [x] 8.2 实现任务创建与状态存储
  - [x] 8.3 实现任务进度追踪
  - [x] 8.4 实现任务结果回调通知
  - [x] 8.5 实现任务超时与清理

- [x] Task 9: 集成AI引擎
  - [x] 9.1 创建 `integration/ai_router.py` - AI路由器
  - [x] 9.2 实现消息到AI引擎的路由
  - [x] 9.3 实现AI回复到微信的转换
  - [x] 9.4 实现流式回复处理（可选）

## Phase 4: API接口扩展

- [x] Task 10: 扩展后端API接口
  - [x] 10.1 新增 `POST /api/skills/weixin/message` - 发送消息
  - [x] 10.2 新增 `POST /api/skills/weixin/task` - 创建异步任务
  - [x] 10.3 新增 `GET /api/skills/weixin/task/{task_id}` - 查询任务状态
  - [x] 10.4 新增 `POST /api/skills/weixin/monitor/start` - 启动监控
  - [x] 10.5 新增 `POST /api/skills/weixin/monitor/stop` - 停止监控
  - [x] 10.6 新增 `GET /api/skills/weixin/monitor/status` - 监控状态

## Phase 5: 前端能力增强

- [x] Task 11: 增强通讯页面消息发送功能
  - [x] 11.1 添加消息发送输入框
  - [x] 11.2 实现消息发送API调用
  - [x] 11.3 实现消息历史展示
  - [x] 11.4 实现发送状态反馈

- [x] Task 12: 实现任务追踪UI
  - [x] 12.1 添加任务创建入口
  - [x] 12.2 实现任务状态轮询
  - [x] 12.3 实现任务进度展示
  - [x] 12.4 实现任务结果展示

- [x] Task 13: 添加调试模式开关
  - [x] 13.1 添加调试模式切换按钮
  - [x] 13.2 实现调试信息展示
  - [x] 13.3 实现耗时统计展示

## Phase 6: 错误处理与监控

- [x] Task 14: 实现错误重试机制
  - [x] 14.1 创建 `utils/retry.py` - 重试策略
  - [x] 14.2 实现指数退避算法
  - [x] 14.3 实现熔断器模式
  - [x] 14.4 实现错误通知发送

- [x] Task 15: 实现性能监控
  - [x] 15.1 创建 `utils/metrics.py` - 性能指标收集
  - [x] 15.2 实现全链路耗时追踪
  - [x] 15.3 实现结构化日志增强
  - [x] 15.4 实现监控指标暴露（可选Prometheus）

## Phase 7: 灰度发布与测试

- [x] Task 16: 实现灰度发布支持
  - [x] 16.1 创建 `config/feature_flags.py` - 功能开关
  - [x] 16.2 实现灰度策略配置
  - [x] 16.3 实现用户分组逻辑
  - [x] 16.4 实现功能回滚机制

- [x] Task 17: 编写单元测试
  - [x] 17.1 消息处理管道测试
  - [x] 17.2 媒体处理测试
  - [x] 17.3 斜杠指令测试
  - [x] 17.4 异步任务测试
  - [x] 17.5 错误重试测试

- [x] Task 18: 编写集成测试
  - [x] 18.1 端到端消息收发测试
  - [x] 18.2 AI对话集成测试
  - [x] 18.3 任务追踪集成测试

- [x] Task 19: 编写上线检查清单与回滚方案
  - [x] 19.1 创建上线检查清单文档
  - [x] 19.2 创建回滚操作手册
  - [x] 19.3 创建监控告警配置

- [ ] Task 20: 微信Android端验证
  - [ ] 20.1 验证文本消息收发
  - [ ] 20.2 验证语音消息处理
  - [ ] 20.3 验证异步任务追踪
  - [ ] 20.4 验证错误恢复机制
  - [ ] 20.5 验证性能指标

# Task Dependencies

- Task 2 依赖 Task 1（监控循环需要消息处理管道）
- Task 3 依赖 Task 1（斜杠指令需要消息处理管道）
- Task 4 依赖 Task 1（格式转换需要消息处理管道）
- Task 5-7 可并行执行（媒体处理模块）
- Task 8-9 可并行执行（异步任务与AI集成）
- Task 10 依赖 Task 1-9（API接口依赖核心能力）
- Task 11-13 依赖 Task 10（前端依赖后端API）
- Task 14-15 可并行执行（错误处理与监控）
- Task 16-20 依赖所有前置任务（灰度与测试）
