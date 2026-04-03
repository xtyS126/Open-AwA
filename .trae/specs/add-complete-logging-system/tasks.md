# Tasks
- [x] Task 1: 盘点现有日志实现并确定统一规范落点
  - [x] SubTask 1.1: 梳理后端现有日志初始化、输出格式与关键埋点位置
  - [x] SubTask 1.2: 梳理前端现有日志/错误上报现状与缺口
  - [x] SubTask 1.3: 形成统一日志字段、级别与敏感信息脱敏清单
  - Task1 输出：前后端日志现状与统一规范
    - 后端现状
      - 日志基础：`backend/main.py` 使用 loguru 初始化全局日志，当前以文本格式输出到 stderr，级别来自 `settings.LOG_LEVEL`。
      - 日志模式：大部分模块使用字符串拼接日志（如 `logger.info(f"...")`），仅微信二维码流程在 `backend/api/routes/skills.py` 使用 `logger.bind(...)` 进行部分结构化字段绑定。
      - 关键埋点：启动/关闭链路、技能执行、插件管理、执行层异常、会话记录落库失败等路径已有埋点，但字段命名不统一、上下文不一致。
      - 缺口：缺少全局 request_id 贯穿、缺少统一结构化字段约束、缺少全局脱敏过滤器。
    - 前端现状
      - 日志基础：未提供统一 logger 封装，页面中以 `console.error` 为主，分散在 App、Settings、Communication、Chat、Plugins、SkillModal 等组件。
      - 请求链路：`frontend/src/services/api.ts` 已有 axios 实例与请求拦截器（注入 Authorization），但未生成/透传 request_id，也未统一记录请求成功/失败日志。
      - 缺口：缺少日志级别控制、缺少统一字段、缺少错误分类与脱敏策略、缺少前后端关联字段。
    - 统一日志字段规范（前后端共用，JSON 结构化）
      - 必填字段：`timestamp`、`level`、`service`、`module`、`event`、`message`、`request_id`。
      - 推荐字段：`user_id_masked`、`session_id`、`action`、`status`、`duration_ms`、`error_code`、`error_type`、`http_method`、`path`、`client_ip_masked`、`trace_id`、`extra`。
      - 字段约束：统一 snake_case；时间使用 ISO8601（UTC）；`request_id` 全链路透传（请求头 `X-Request-Id`，无则生成）。
    - 统一日志级别规范
      - `DEBUG`：仅开发排查，记录详细上下文，不含敏感明文。
      - `INFO`：关键业务里程碑（启动、登录成功、调用成功、状态切换）。
      - `WARNING`：可恢复异常或降级路径（重试、回退、第三方短暂失败）。
      - `ERROR`：影响当前请求或业务失败，需携带 `error_type`、`error_code`、`request_id`。
      - `CRITICAL`：系统级故障（服务不可用、数据损坏、核心依赖不可达）。
    - 敏感信息脱敏规范
      - 高敏字段（禁止明文）：`password`、`token`、`api_key`、`secret`、`authorization`、`cookie`、`access_token`、`refresh_token`。
      - 标识类字段（掩码输出）：`user_id`、`account_id`、`phone`、`email`、`ip`、`openid`。
      - 脱敏策略：默认白名单输出；字典键名命中敏感词即替换为 `***`；长串凭据仅保留前 2 后 2；URL 查询参数中敏感键统一脱敏；异常日志禁止原样输出请求体。

- [x] Task 2: 实现后端统一日志基础设施
  - [x] SubTask 2.1: 建立统一日志初始化与配置读取能力
  - [x] SubTask 2.2: 在 API 入口注入 request_id 并贯穿关键调用链
  - [x] SubTask 2.3: 将关键模块日志改造为结构化输出（登录、对话、技能、异常路径）
  - [x] SubTask 2.4: 增加敏感字段脱敏处理

- [x] Task 3: 实现前端日志与错误采集能力
  - [x] SubTask 3.1: 增加前端统一日志封装与级别控制
  - [x] SubTask 3.2: 增加页面访问、关键操作与错误日志埋点
  - [x] SubTask 3.3: 透传并记录 request_id，实现前后端日志关联

- [x] Task 4: 增加日志检索与导出最小能力
  - [x] SubTask 4.1: 设计日志查询接口参数与响应结构
  - [x] SubTask 4.2: 实现按时间范围/级别/关键字筛选
  - [x] SubTask 4.3: 实现日志导出接口（JSONL）

- [x] Task 5: 验证与质量保障
  - [x] SubTask 5.1: 为后端日志链路与脱敏规则补齐测试
  - [x] SubTask 5.2: 为前端日志封装与错误采集补齐必要验证
  - [x] SubTask 5.3: 运行项目 lint、typecheck、测试并修复问题
  - [x] SubTask 5.4: 回填 checklist.md 全量检查项

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 2
- Task 5 依赖 Task 2、Task 3、Task 4
