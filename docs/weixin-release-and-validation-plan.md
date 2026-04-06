# 微信 AI 交互上线检查与回滚方案

## 上线检查清单

- [ ] 后端环境变量与数据库迁移已完成，`/api/skills/weixin/config` 可读写
- [ ] 微信扫码登录链路可用，`qr/start` 与 `qr/wait` 状态机正常
- [ ] 消息发送接口 `/api/skills/weixin/message` 返回成功并可在微信端收到消息
- [ ] 异步任务接口 `/api/skills/weixin/task` 可创建并轮询至 `completed`
- [ ] 监控接口 `/api/skills/weixin/monitor/start|status|stop` 可正常调用
- [ ] 错误重试与熔断日志可在后端日志中检索到
- [ ] 前端通讯页可发送消息、创建任务、查看任务状态与调试信息

## 灰度发布方案

1. 启用功能开关 `weixin_ai_interaction_v2`，初始灰度比例 `10%`
2. 观察 30 分钟核心指标：消息成功率、任务完成率、错误率、平均延迟
3. 指标稳定后按 `10% -> 30% -> 50% -> 100%` 逐步放量
4. 每次放量前后执行一次接口冒烟：
   - `POST /api/skills/weixin/message`
   - `POST /api/skills/weixin/task`
   - `GET /api/skills/weixin/monitor/status`

## 回滚方案

1. 将 `weixin_ai_interaction_v2` 开关置为 `enabled=false`
2. 停止微信监控：`POST /api/skills/weixin/monitor/stop`
3. 将流量切回旧消息链路（原 `skills.weixin_skill_adapter`）
4. 保留任务数据文件，避免任务状态丢失
5. 回滚后执行冒烟验证：
   - 扫码登录
   - 文本消息发送
   - 基础健康检查

## Android 端验证步骤

1. 使用微信 Android 客户端扫码并确认授权
2. 发送自然语言问题，确认实时文本回复
3. 发送任务指令（如深度检索），确认任务创建与进度更新
4. 人为制造网络抖动，确认重试与错误提示
5. 验证调试模式下耗时输出是否存在并可读

## 观测指标建议

- 消息发送成功率 >= 99%
- 任务完成率 >= 95%
- P95 响应时延 <= 3 秒
- 熔断触发次数与恢复次数可追踪

