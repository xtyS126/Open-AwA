# Tasks
- [x] Task 1: 审阅 `weixin-ilink` README 与源码，建立替换范围
  - [x] SubTask 1.1: 解析 README 中的登录、客户端、轮询、发送、配置、上传能力与运行前提
  - [x] SubTask 1.2: 盘点当前项目中全部 weixin 相关入口、后端适配层、前端页面、API 契约与测试文件
  - [x] SubTask 1.3: 形成“新实现覆盖旧实现”的替换矩阵，明确哪些代码需要保留、改写或删除

- [ ] Task 2: 用 `weixin-ilink` 重构后端 weixin 集成
  - [ ] SubTask 2.1: 以 `loginWithQR` 语义重构二维码登录开始、轮询、超时、刷新与成功凭据回填逻辑
  - [ ] SubTask 2.2: 以 `ILinkClient` 或低阶 API 语义重构消息轮询、发送、配置获取与必要状态持久化
  - [ ] SubTask 2.3: 清理或删除已被替换的旧后端 weixin 兼容逻辑与无效分支

- [ ] Task 3: 用 `weixin-ilink` 重构前端通讯页与 API 契约
  - [ ] SubTask 3.1: 对齐前端登录状态、二维码展示、超时/过期提示与成功态回填字段
  - [ ] SubTask 3.2: 更新前端 API 类型、请求响应结构与页面状态机
  - [ ] SubTask 3.3: 删除对旧 weixin 状态名、旧字段名与旧提示流程的依赖

- [ ] Task 4: 清理旧实现并补齐验证
  - [ ] SubTask 4.1: 删除或重写与 `weixin-ilink` 新方案冲突的旧 weixin 代码与旧测试
  - [ ] SubTask 4.2: 新增或更新后端测试与前端测试，覆盖二维码登录、消息收发、游标与异常路径
  - [ ] SubTask 4.3: 运行相关测试、类型检查、lint 与必要构建校验，修复全部失败项

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
