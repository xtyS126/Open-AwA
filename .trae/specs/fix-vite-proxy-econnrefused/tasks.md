# Tasks

- [x] Task 1: 验证后端服务启动状态
  - [x] SubTask 1.1: 检查端口 8000 是否有服务监听
  - [x] SubTask 1.2: 尝试访问后端健康检查接口
  - [x] SubTask 1.3: 确认后端依赖是否已安装

- [x] Task 2: 启动后端服务
  - [x] SubTask 2.1: 进入后端目录并激活虚拟环境
  - [x] SubTask 2.2: 安装依赖（如需要）
  - [x] SubTask 2.3: 启动后端服务

- [x] Task 3: 验证前后端联调
  - [x] SubTask 3.1: 确认后端健康检查返回正常
  - [x] SubTask 3.2: 确认前端代理请求不再报错
  - [x] SubTask 3.3: 验证登录和计费接口正常响应

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
