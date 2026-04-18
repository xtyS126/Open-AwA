# Tasks

- [ ] Task 1: 集成ChromaDB向量数据库，实现记忆向量化存储与检索
  - [ ] SubTask 1.1: 安装chromadb依赖并配置向量存储后端
  - [ ] SubTask 1.2: 创建VectorStoreManager类，封装ChromaDB操作（添加/搜索/删除向量）
  - [ ] SubTask 1.3: 集成嵌入模型（支持OpenAI和本地sentence-transformers）
  - [ ] SubTask 1.4: 修改LongTermMemory保存时自动向量化并存储到ChromaDB
  - [ ] SubTask 1.5: 实现向量语义搜索接口，支持混合检索（关键词+向量）
  - [ ] SubTask 1.6: 编写VectorStoreManager单元测试，覆盖率>=95%

- [ ] Task 2: 增强记忆分层架构与质量保障
  - [ ] SubTask 2.1: 实现工作内存层（WorkingMemory），基于内存缓存+LRU淘汰
  - [ ] SubTask 2.2: 实现记忆自动归档策略（基于时间和重要性）
  - [ ] SubTask 2.3: 实现置信度动态衰减算法
  - [ ] SubTask 2.4: 实现记忆质量评分系统（综合来源/完整性/时效性）
  - [ ] SubTask 2.5: 编写记忆管理增强测试，覆盖率>=95%

- [ ] Task 3: 扩展记忆管理API
  - [ ] SubTask 3.1: 新增 /api/memory/vector-search 向量搜索接口
  - [ ] SubTask 3.2: 新增 /api/memory/archive 记忆归档接口
  - [ ] SubTask 3.3: 新增 /api/memory/quality 质量评估接口
  - [ ] SubTask 3.4: 新增 /api/memory/stats 记忆统计接口（增强版）
  - [ ] SubTask 3.5: 编写API集成测试，覆盖率>=95%

- [ ] SubTask 4.1: 创建工作流数据模型（Workflow, WorkflowStep, WorkflowExecution）
- [ ] SubTask 4.2: 实现工作流解析器（YAML/JSON格式）
- [ ] SubTask 4.3: 实现工作流执行引擎（顺序执行、条件分支、异常处理）
- [ ] SubTask 4.4: 实现工作流与Skill/Plugin的集成
- [ ] SubTask 4.5: 编写工作流引擎单元测试，覆盖率>=95%

- [ ] Task 5: 扩展内置工具集
  - [ ] SubTask 5.1: 实现FileManager工具（read/write/edit/list）
  - [ ] SubTask 5.2: 实现TerminalExecutor工具（沙箱命令执行）
  - [ ] SubTask 5.3: 实现WebSearch工具（网页搜索）
  - [ ] SubTask 5.4: 注册工具到SkillRegistry
  - [ ] SubTask 5.5: 编写内置工具测试，覆盖率>=95%

- [ ] Task 6: 集成到Agent主流程
  - [ ] SubTask 6.1: 在AIAgent.process中集成向量检索获取相关记忆
  - [ ] SubTask 6.2: 在AIAgent中注入工作流执行能力
  - [ ] SubTask 6.3: 更新Agent上下文构建，包含向量检索的记忆
  - [ ] SubTask 6.4: 编写Agent集成测试

- [ ] Task 7: 更新文档
  - [ ] SubTask 7.1: 更新API文档，新增记忆和工作流接口说明
  - [ ] SubTask 7.2: 更新部署手册，增加ChromaDB配置说明
  - [ ] SubTask 7.3: 更新用户操作指南，说明新功能使用方法

- [ ] Task 8: 运行全量测试并验证
  - [ ] SubTask 8.1: 运行backend pytest，确保所有测试通过
  - [ ] SubTask 8.2: 验证测试覆盖率>=95%
  - [ ] SubTask 8.3: 运行lint检查，确保代码规范

# Task Dependencies

- Task 2 依赖 Task 1（记忆分层需要向量存储基础）
- Task 3 依赖 Task 1 和 Task 2（API需要底层功能实现）
- Task 4 独立（工作流引擎可并行开发）
- Task 5 依赖 Task 4（工具需要注册到系统）
- Task 6 依赖 Task 1, 2, 3, 4, 5（集成需要所有功能就绪）
- Task 7 依赖 Task 3, 4, 5（文档需要功能实现）
- Task 8 依赖所有其他任务
