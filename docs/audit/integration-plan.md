# Open-AwA 开源库集成方案

> 文档日期：2026-04-24
> 前置文档：
>   - [竞品调研报告](competitive-research.md)
>   - [开源库评估报告](open-source-evaluation.md)
>   - [后端架构说明](../backend-architecture.md)

---

## 目录

1. [候选库筛选结果](#1-候选库筛选结果)
2. [集成架构设计](#2-集成架构设计)
3. [数据模型映射](#3-数据模型映射)
4. [配置合并方案](#4-配置合并方案)
5. [冲突解决策略](#5-冲突解决策略)
6. [集成方案对比](#6-集成方案对比)

---

## 1. 候选库筛选结果

### Top 3 候选库

| 排名 | 库名 | 加权得分 | 核心定位 | 推荐度 |
|:----:|------|:--------:|----------|:------:|
| 1 | **LlamaIndex** | 7.75 | 数据连接与 RAG 检索 | 强烈推荐 |
| 2 | **CrewAI** | 7.15 | 多 Agent 协作编排 | 推荐 |
| 3 | **Agno** | 7.10 | 高性能 Agent 运行时 | 推荐（场景特定） |

### 选择理由

#### 第 1 名：LlamaIndex（7.75 分）

**选择理由：**
- **RAG 检索精度最高（92%）**：在 Open-AwA 最核心的知识库检索场景上表现最优，显著优于 LangChain（85%）
- **300+ 数据连接器**：可直接对接项目当前 `SimpleDirectoryReader` + 本地文件的数据接入模式，并支持扩展到数据库、API、SaaS 等多种数据源
- **安全记录良好**：无公开重大 CVE，对比 LangChain 的多个高危漏洞（CVSS 9.3 反序列化漏洞），安全性有保障
- **MIT 许可证**：无商业使用限制，与项目当前的许可证策略一致
- **轻量级架构**：支持按需导入，不会对现有 FastAPI 应用带来不必要的重量级依赖
- **与现有技术栈匹配**：当前项目已使用 ChromaDB（通过 `vector_store_manager.py`），LlamaIndex 原生支持 ChromaDB 作为向量存储后端，迁移成本低

**定位**：作为 Open-AwA 的**数据层和 RAG 检索引擎**，增强知识库能力

#### 第 2 名：CrewAI（7.15 分）

**选择理由：**
- **纯 Python，MIT 许可证**：商业最友好，零 LangChain 依赖（v1.x 完全重写）
- **角色化 Agent 编排**：与 Open-AwA 当前的 `AIAgent` 流程（理解-规划-执行-反馈）互补，可增强多 Agent 协作场景
- **企业采用率高**：60% 财富 500 强使用，生产环境验证充分
- **轻量级**：作为库集成，不会对现有 FastAPI 架构造成侵入性修改
- **互补而非替代**：不与现有 `SkillEngine`/`PluginManager` 发生职责冲突，而是增强上层编排能力

**定位**：作为 Open-AwA 的**多 Agent 协作编排层**，用于复杂任务的角色化分解与执行

#### 第 3 名：Agno（7.10 分）

**选择理由：**
- **极致性能**：Agent 实例化仅 2μs（比 LangGraph 快 10,000x），适合高并发场景
- **极低内存占用**：每个 Agent 仅 3.75KiB（比 LangGraph 少 50x），适合资源受限部署
- **Apache-2.0 许可证**：商业友好
- **多模态原生支持**：文本、图像、音频、视频统一处理

**定位**：作为 Open-AwA 的**高性能 Agent 运行时备选**，当遇到性能瓶颈时替代 CrewAI

---

## 2. 集成架构设计

### 2.1 整体架构总览

```
+------------------------------------------------------------------+
|                        Open-AwA API Layer                         |
|  (FastAPI Routes: chat.py, skills.py, plugins.py, memory.py ...)  |
+------------------------------------------------------------------+
        |                        |                          |
        v                        v                          v
+-------------------+  +-------------------+  +-------------------------+
|   AISAgent Core   |  |   SkillEngine     |  |    PluginManager        |
| (agent.py 主流程)  |  | (技能执行引擎)     |  |   (插件管理系统)         |
+-------------------+  +-------------------+  +-------------------------+
        |                        |                          |
        v                        v                          v
+---------------------------------------------------------------+
|                   Anti-Corruption Layer (防腐层)                |
|  +------------------+  +------------------+  +---------------+  |
|  | LlamaIndex       |  | CrewAI/Agno      |  | LiteLLM       |  |
|  | Adapter          |  | Adapter          |  | (已有)        |  |
|  +------------------+  +------------------+  +---------------+  |
+---------------------------------------------------------------+
        |                        |
        v                        v
+-------------------+  +-------------------+
|   LlamaIndex      |  |   CrewAI/Agno     |
|   (数据/RAG 引擎)  |  | (多 Agent 编排)   |
+-------------------+  +-------------------+
```

### 2.2 防腐层 (Anti-Corruption Layer) 设计

防腐层位于 Open-AwA 核心业务逻辑与第三方库之间，确保：

1. **业务隔离**：第三方库的 API 变更不会直接传播到核心业务代码
2. **接口统一**：对外暴露 Open-AwA 风格的方法签名，内部完成协议转换
3. **依赖倒置**：核心代码仅依赖抽象接口，不依赖具体实现

#### LlamaIndex 防腐层

```
核心代码（依赖抽象）        防腐层（适配转换）          第三方库
+-------------+        +-------------------+        +------------+
|             | ---->  | LlamaIndexAdapter | ---->  | LlamaIndex |
| Memory/     | <----  |                   | <----  | (数据连接)  |
| RAG 使用方  |        | + build_index()   |        +------------+
|             |        | + query_engine()  |
+-------------+        | + ingest_docs()   |
                       +-------------------+
```

```python
# 防腐层抽象接口（位于 backend/core/rag_adapter.py）
class RAGAdapter(ABC):
    """RAG 数据层抽象接口，供核心业务代码调用"""

    @abstractmethod
    async def ingest_documents(
        self, documents: List[Dict[str, Any]], user_id: Optional[str] = None
    ) -> IngestResult:
        ...

    @abstractmethod
    async def query(
        self, query_text: str, user_id: Optional[str] = None, top_k: int = 5
    ) -> QueryResult:
        ...

    @abstractmethod
    async def delete_document(
        self, document_id: str, user_id: Optional[str] = None
    ) -> bool:
        ...

# LlamaIndex 具体实现（位于 backend/core/rag_adapters/llama_index_adapter.py）
class LlamaIndexAdapter(RAGAdapter):
    """LlamaIndex 的防腐层实现，封装所有 LlamaIndex 调用"""

    def __init__(self, config: LlamaIndexConfig):
        self._config = config
        self._indices: Dict[str, VectorStoreIndex] = {}

    async def ingest_documents(self, documents, user_id=None):
        # 内部调用 LlamaIndex 的 SimpleDirectoryReader / VectorStoreIndex
        ...

    async def query(self, query_text, user_id=None, top_k=5):
        # 内部调用 LlamaIndex 的 QueryEngine
        ...
```

#### CrewAI/Agno 防腐层

```
核心代码（依赖抽象）        防腐层（适配转换）          第三方库
+-------------+        +-------------------+        +------------+
|             | ---->  | AgentOrchestrator | ---->  | CrewAI     |
| AIAgent     | <----  |                   | <----  | (多 Agent)  |
| (agent.py)  |        | + create_crew()   |        +------------+
|             |        | + run_agents()    |
+-------------+        | + stop_agents()   |
                       +-------------------+
```

```python
# 防腐层抽象接口（位于 backend/core/agent_orchestrator.py）
class AgentOrchestrator(ABC):
    """多 Agent 编排抽象接口"""

    @abstractmethod
    async def create_crew(
        self, agents: List[AgentDefinition], tasks: List[TaskDefinition]
    ) -> CrewHandle:
        ...

    @abstractmethod
    async def run_crew(self, handle: CrewHandle) -> CrewResult:
        ...

    @abstractmethod
    async def stop_crew(self, handle: CrewHandle) -> None:
        ...
```

### 2.3 适配器模式 (Adapter Pattern) 实现方案

当前 Open-AwA 的代码结构已经隐含了适配器模式的需求，具体实现路径如下：

| 适配器 | 源接口（第三方） | 目标接口（Open-AwA） | 关键转换逻辑 |
|--------|-----------------|---------------------|-------------|
| `LlamaIndexAdapter` | `VectorStoreIndex.query()` | `RAGAdapter.query()` | 将 LlamaIndex 的 `QueryBundle` 转换为 Open-AwA 的 `QueryResult` |
| `CrewAIAdapter` | `Crew.kickoff()` | `AgentOrchestrator.run_crew()` | 将 CrewAI 的 `Agent/Task` 定义映射到 Open-AwA 的 `AgentDefinition/TaskDefinition` |
| `DocumentAdapter` | `SimpleDirectoryReader.load_data()` | `RAGAdapter.ingest_documents()` | 将 LlamaIndex 的 `Document` 对象转换为 Open-AwA 的统一文档格式 |

### 2.4 接口隔离原则 (Interface Segregation) 的应用

针对每个候选库的功能范围，设计细粒度的接口，避免"胖接口"：

```python
# 细粒度接口设计

class DocumentIngestor(ABC):
    """仅负责文档摄入，不涉及查询"""

    async def ingest(self, documents: list) -> IngestResult: ...


class QueryExecutor(ABC):
    """仅负责检索查询，不涉及文档管理"""

    async def query(self, query_text: str) -> QueryResult: ...


class IndexManager(ABC):
    """仅负责索引生命周期管理"""

    async def create_index(self, config: IndexConfig) -> str: ...
    async def delete_index(self, index_id: str) -> bool: ...
    async def rebuild_index(self, index_id: str) -> bool: ...


class AgentCoordinator(ABC):
    """仅负责 Agent 协调，不涉及 RAG"""

    async def assign_task(self, task: TaskDefinition) -> TaskHandle: ...
    async def get_status(self, handle: TaskHandle) -> TaskStatus: ...
```

### 2.5 依赖倒置 (Dependency Inversion) 的具体做法

**当前现状**：`AIAgent` 类直接实例化 `SkillEngine`、`PluginManager`、`MemoryManager` 等具体类。

**改造目标**：通过依赖注入（DI）将具体实现替换为抽象依赖。

```python
# 当前写法（高耦合）
class AIAgent:
    def __init__(self, db_session: Session = None):
        self.comprehension = ComprehensionLayer()       # 具体实现
        self.planner = PlanningLayer()                  # 具体实现
        self.executor = ExecutionLayer()                # 具体实现
        self.skill_engine = SkillEngine(self._db_session)  # 具体实现

# 改造后写法（依赖倒置）
class AIAgent:
    def __init__(
        self,
        db_session: Session = None,
        rag_adapter: Optional[RAGAdapter] = None,           # 依赖抽象
        orchestrator: Optional[AgentOrchestrator] = None,    # 依赖抽象
    ):
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self._rag_adapter = rag_adapter or NullRAGAdapter()    # 注入或空实现
        self._orchestrator = orchestrator or NullOrchestrator()

    async def process_with_rag(self, query: str, context: dict) -> dict:
        """使用 RAG 增强的查询处理"""
        if self._rag_adapter:
            rag_results = await self._rag_adapter.query(query, ...)
            context["rag_context"] = rag_results
        return await self.process(query, context)
```

依赖注入的配置化组装：

```python
# 依赖注入配置（位于 backend/core/di_config.py 或在 main.py 的 lifespan 中）
def configure_agent_services(settings, db_session):
    """根据配置组装 AIAgent 的依赖项"""

    # RAG 适配器
    if settings.ENABLE_LLAMA_INDEX:
        rag_adapter = LlamaIndexAdapter(
            config=LlamaIndexConfig(
                vector_store_type=settings.VECTOR_STORE_TYPE,  # chroma / pinecone / qdrant
                embedding_model=settings.EMBEDDING_MODEL,
                chunk_size=settings.CHUNK_SIZE,
            )
        )
    else:
        rag_adapter = None  # 使用 Null 对象

    # Agent 编排适配器
    if settings.ENABLE_CREWAI:
        orchestrator = CrewAIAdapter(
            config=CrewAIConfig(
                llm_provider=settings.LLM_PROVIDER,
                llm_model=settings.LLM_MODEL,
            )
        )
    else:
        orchestrator = None

    return AIAgent(
        db_session=db_session,
        rag_adapter=rag_adapter,
        orchestrator=orchestrator,
    )
```

### 2.6 与现有代码的边界划分

```
+--------------------------------------------------------------------+
|                        Open-AwA 核心代码                             |
|  (不应直接感知 LlamaIndex / CrewAI / Agno 的存在)                   |
+--------------------------------------------------------------------+
          |                      |                    |
          | (通过抽象接口调用)    |                    |
          v                      v                    v
+------------------+  +------------------+  +------------------+
|  RAGAdapter      |  | AgentOrchestrator|  | MemoryManager    |
|  (抽象接口)       |  | (抽象接口)        |  | (已有)           |
+------------------+  +------------------+  +------------------+
          |                      |
          | (通过配置可插拔)      |
          v                      v
+------------------+  +------------------+
| LlamaIndexAdapter|  | CrewAIAdapter    |
| (防腐层实现)      |  | (防腐层实现)      |
+------------------+  +------------------+
          |                      |
          v                      v
+------------------+  +------------------+
| LlamaIndex       |  | CrewAI / Agno   |
| (第三方库)        |  | (第三方库)        |
+------------------+  +------------------+
          |
          v
+------------------+
| ChromaDB(已有)   |
| / Pinecone /     |
| Qdrant           |
+------------------+
```

**边界划分规则：**

| 边界 | 左侧（核心代码） | 右侧（适配器/第三方库） |
|------|-----------------|----------------------|
| 文件位置 | `backend/core/` | `backend/core/rag_adapters/`、`backend/core/orchestrators/` |
| 导入路径 | 仅引用 `abc.ABC` 定义的接口 | 可引用 `llama_index`、`crewai` 等第三方包 |
| 异常类型 | 仅抛出 `OpenAwAException` 子类 | 在适配器内部捕获第三方异常并转换 |
| 数据格式 | Pydantic 模型（`schemas.py`） | 在适配器内部完成格式映射 |
| 测试策略 | Mock 接口进行单元测试 | 集成测试（含真实第三方库） |

---

## 3. 数据模型映射

### 3.1 字段兼容性映射表

#### LlamaIndex Document -> Open-AwA 文档模型

| LlamaIndex 字段 | Open-AwA 对应字段 | 兼容性 | 映射策略 |
|----------------|-------------------|--------|---------|
| `Document.text` | `LongTermMemory.content` | 直接兼容 | 直接赋值 |
| `Document.doc_id` | `LongTermMemory.id` | 需转换 | `doc_id` 为 str，`id` 为 int，需建立外部 ID 映射表 |
| `Document.metadata` | `LongTermMemory.memory_metadata` | 直接兼容 | 均为 JSON 格式 |
| `Document.embedding` | `LongTermMemory.embedding` | 直接兼容 | 均为 `List[float]` |
| `IndexStruct.index_id` | 无直接对应 | 需新增 | 在 `LongTermMemory` 中新增 `index_id` 字段或使用外部映射 |
| `NodeRelation` | 无直接对应 | 需新增 | Open-AwA 尚未建立文档间关系模型，需新增 `DocumentRelation` 表 |

#### LlamaIndex VectorStore -> Open-AwA ChromaDB

| LlamaIndex 概念 | Open-AwA 当前实现 | 兼容性 | 说明 |
|----------------|-------------------|--------|------|
| `ChromaVectorStore` | `backend/memory/vector_store_manager.py` | 直接兼容 | 均基于 ChromaDB，可共享同一集合 |
| `collection_name` | `collection_name` 参数 | 直接兼容 | 命名规则需统一 |
| `persist_dir` | `settings.VECTOR_DB_PATH` | 直接兼容 | 当前已配置 `VECTOR_DB_PATH` |
| `embedding_model` | `settings.EMBEDDING_MODEL`（若未来新增） | 需新增配置 | 当前未显式配置 embedding 模型 |

#### CrewAI Agent/Task -> Open-AwA 角色/任务模型

| CrewAI 概念 | Open-AwA 当前实现 | 兼容性 | 映射策略 |
|------------|-------------------|--------|---------|
| `Agent(role, goal, backstory)` | 无直接对应 | 需新增 | 新增 `AgentProfile` 表存储角色定义 |
| `Agent.tools` | `Skill` / `Plugin` | 间接兼容 | 将 Open-AwA 的技能/插件包装为 CrewAI 工具 |
| `Agent.llm` | `model_service.py` / `litellm_adapter.py` | 需适配 | 通过 LiteLLM 接口提供 LLM 实例 |
| `Task(description, agent)` | `WorkflowStep` | 间接兼容 | 将 `Task` 映射为 `WorkflowStep`，并在 `WorkflowExecution` 中记录 |
| `Crew(agents, tasks)` | `Workflow` | 间接兼容 | 将 `Crew` 映射为 `Workflow` 定义 |

### 3.2 枚举类型转换方案

需要考虑的枚举/常量映射：

| Open-AwA 枚举 | 候选库对应值 | 转换策略 |
|--------------|------------|---------|
| `memory.archive_status`（`active`/`archived`） | LlamaIndex 无直接对应 | 在适配器中过滤归档文档 |
| `User.role`（`admin`/`user`） | 无对应 | 保持独立，不参与映射 |
| `status` 字段（`success`/`failed`/`pending`） | CrewAI `Task.status` | 建立双向映射表 |
| `WorkflowStep.step_type` | CrewAI `Task.process_type` | 枚举值转换函数 |

```python
# 枚举映射配置（位于对应适配器中）
STATUS_MAPPING = {
    CrewAITaskStatus.PENDING: "pending",
    CrewAITaskStatus.RUNNING: "running",
    CrewAITaskStatus.COMPLETED: "success",
    CrewAITaskStatus.FAILED: "failed",
}
REVERSE_STATUS_MAPPING = {v: k for k, v in STATUS_MAPPING.items()}
```

### 3.3 版本演进策略

采用**三阶段演进策略**：

```
阶段一：共存期（v1.x）
  - 现有 `MemoryManager` / `vector_store_manager.py` 继续运行
  - LlamaIndex 以旁路方式部署，仅在特定接口启用
  - 数据双向同步（现有 ChromaDB 同时通过 LlamaIndex 写入）

阶段二：迁移期（v2.x）
  - 新增接口默认走 LlamaIndex（`RAGAdapter` 统一入口）
  - 旧接口保留兼容模式（通过配置开关切换后端）
  - 数据逐步迁移到 LlamaIndex 管理

阶段三：标准期（v3.x）
  - 移除旧实现，全面使用 LlamaIndex
  - 废弃旧接口，保留兼容包装器
  - 可通过配置选择不同的向量存储后端
```

### 3.4 迁移脚本方案

```python
# 迁移脚本示例（位于 backend/scripts/migrate_to_llamaindex.py）
"""
将现有 ChromaDB 中的向量数据迁移到 LlamaIndex 索引。
在阶段一和阶段二之间执行，确保数据不丢失。
"""

async def migrate_vector_store():
    """将现有 ChromaDB 集合迁移到 LlamaIndex 索引"""

    # 1. 从现有 ChromaDB 读取所有文档
    existing_docs = await read_existing_chroma_collection()

    # 2. 转换为 LlamaIndex Document 格式
    llama_docs = [
        Document(
            text=doc.content,
            metadata={
                "id": doc.id,
                "user_id": doc.user_id,
                "importance": doc.importance,
                "original_embedding": doc.embedding,
            },
        )
        for doc in existing_docs
    ]

    # 3. 构建 LlamaIndex 索引
    index = VectorStoreIndex.from_documents(
        llama_docs,
        embed_model=embed_model,
        storage_context=storage_context,
    )

    # 4. 持久化索引
    index.storage_context.persist(persist_dir=VECTOR_DB_PATH)

    # 5. 记录迁移日志
    logger.info(f"迁移完成: {len(llama_docs)} 个文档")

    return MigrationResult(total=len(llama_docs), status="completed")
```

---

## 4. 配置合并方案

### 4.1 环境变量冲突解决方案

当前 `settings.py` 中的环境变量与候选库的环境变量冲突分析：

| 环境变量名 | Open-AwA 位置 | LlamaIndex 相关 | CrewAI 相关 | 冲突风险 |
|-----------|--------------|----------------|-------------|---------|
| `OPENAI_API_KEY` | `settings.OPENAI_API_KEY` | 通过 `Settings` 对象传入 | 通过 `LLM` 对象传入 | 低（值相同，使用场景不同） |
| `ANTHROPIC_API_KEY` | `settings.ANTHROPIC_API_KEY` | 无需直接使用 | 通过 `LLM` 对象传入 | 低 |
| `DATABASE_URL` | `settings.DATABASE_URL` | 无需直接使用 | 无需直接使用 | 无 |
| `VECTOR_DB_PATH` | `settings.VECTOR_DB_PATH` | 需传入 `persist_dir` | 无需使用 | 低（需统一路径） |

**冲突解决原则：**

1. Open-AwA 的环境变量优先级最高，第三方库的配置通过适配器从其获取
2. LlamaIndex/CrewAI 不直接读取 `os.environ`，而是通过适配器的配置对象传入
3. 共用资源（如向量数据库路径）通过 `settings` 对象统一管理，防止路径不一致

```python
# 配置隔离方案（适配器中）
class LlamaIndexConfig:
    """从 Open-AwA 设置中提取 LlamaIndex 所需配置，不直接读环境变量"""

    def __init__(self, settings: Settings):
        self.vector_db_path = settings.VECTOR_DB_PATH
        self.openai_api_key = settings.OPENAI_API_KEY.get_secret_value()
        # 不从环境变量读取，仅从 settings 对象获取
```

### 4.2 YAML 配置合并策略

当前项目使用 YAML 配置技能定义（`skills/configs/*.yaml`），候选库也使用 YAML 格式：

| 配置类型 | 当前位置 | 候选库格式 | 合并策略 |
|---------|---------|-----------|---------|
| 技能定义 | `backend/skills/configs/*.yaml` | CrewAI 无直接对应 | 保持独立，无需合并 |
| 工作流定义 | `Workflow.definition`（DB JSON 字段） | CrewAI `Crew` 配置 | 将 CrewAI 配置存储为 `Workflow.definition` 的子集 |
| 索引配置 | 无（当前硬编码） | LlamaIndex `StorageContext` | 新增 `backend/config/index_config.yaml` |

**合并示例：**

```yaml
# backend/config/index_config.yaml（新增）
# LlamaIndex 索引配置，保持与 Open-AwA 设置的统一

vector_store:
  type: chroma  # chroma / pinecone / qdrant
  persist_dir: ${VECTOR_DB_PATH}
  collection_prefix: "openawa_"

embedding:
  model: "text-embedding-3-small"
  dimensions: 1536
  batch_size: 100

chunking:
  chunk_size: 512
  chunk_overlap: 50
  strategy: "sentence"  # sentence / token / recursive
```

### 4.3 .env 文件管理方案

当前 `.env` / `.env.local` 文件管理规则：

```bash
# backend/.env（公共配置，可提交到仓库）
# 不包含敏感信息，仅记录键名
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=

# 以下为候选库相关的新增环境变量键名
# LlamaIndex（可选配置）
LLAMA_INDEX_ENABLED=false
VECTOR_STORE_TYPE=chroma
EMBEDDING_MODEL=text-embedding-3-small

# CrewAI（可选配置）
CREWAI_ENABLED=false
CREWAI_MAX_AGENTS=5
CREWAI_TASK_TIMEOUT=300
```

```bash
# backend/.env.local（本地覆盖，不可提交）
# 本地开发环境的密钥和覆盖配置
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 4.4 与 K8s ConfigMap/Secret 的集成方式

```yaml
# K8s ConfigMap 示例（openawa-config.yaml）
apiVersion: v1
kind: ConfigMap
metadata:
  name: openawa-config
data:
  # 应用核心配置
  DATABASE_URL: "postgresql://..."
  VECTOR_DB_PATH: "/data/vector_db"

  # LlamaIndex 配置
  LLAMA_INDEX_ENABLED: "true"
  VECTOR_STORE_TYPE: "chroma"
  EMBEDDING_MODEL: "text-embedding-3-small"

  # CrewAI 配置
  CREWAI_ENABLED: "true"
  CREWAI_MAX_AGENTS: "5"

---
# K8s Secret 示例
apiVersion: v1
kind: Secret
metadata:
  name: openawa-secrets
type: Opaque
stringData:
  OPENAI_API_KEY: "sk-xxx"
  ANTHROPIC_API_KEY: "sk-ant-xxx"
```

**关键原则**：第三方库的配置始终通过 Open-AwA 的 `settings` 对象间接获取，不直接从环境变量读取，确保 K8s 环境中配置来源统一。

---

## 5. 冲突解决策略

### 5.1 重复路由问题

**潜在冲突：** 候选库可能自带 HTTP 服务（如 LlamaIndex 的 `QueryEngine` 内部调用在线 API），与 FastAPI 路由产生重叠。

**解决策略：**

| 冲突场景 | 风险等级 | 解决措施 |
|---------|---------|---------|
| LlamaIndex 通过 HTTP 调用 LLM API | 低 | 使用当前已有的 `litellm_adapter.py` 统一管理 LLM 调用，不让 LlamaIndex 直接管理 API 调用 |
| CrewAI 自带 Dashboard 服务 | 中 | 在适配器层禁用 CrewAI 的内置 Web 服务（`CrewAI(share=False)`），使用 Open-AwA 现有的 WebSocket 和 REST API |
| 模型列表 API 重叠 | 低 | 统一使用 `litellm_adapter.py` 的 `litellm_list_models` 方法，候选库不直接调用供应商 API |

### 5.2 端口占用检测

**潜在冲突：** 候选库默认占用的端口与 Open-AwA 冲突。

| 候选库 | 默认端口 | Open-AwA 默认端口 | 冲突可能性 | 解决措施 |
|-------|---------|------------------|-----------|---------|
| LlamaIndex（Lib 模式） | 无 | 8000 | 无 | 以库方式使用，不启动独立服务 |
| CrewAI（Flows 模式） | 无 | 8000 | 无 | 以库方式使用，不启动独立服务 |
| Agno Dashboard | 7777 | 8000 | 低 | 在适配器中禁用 Dashboard |

**端口检测工具：**

```python
# 适配器中的端口检测逻辑
def check_port_available(host: str, port: int) -> bool:
    """检查端口是否可用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False
```

### 5.3 日志格式统一

当前使用 **Loguru**（`from loguru import logger`），候选库日志格式不一致：

| 日志源 | 当前格式 | 候选库格式 | 统一方案 |
|-------|---------|-----------|---------|
| Open-AwA | Loguru（结构化 `bind` + 格式化） | Python `logging` 模块 | 通过 `logging` -> `loguru` 桥接 |
| LlamaIndex | Python `logging` | `logging` | 添加 Logging Handler 重定向 |
| CrewAI | `rich` 控制台 + `logging` | `logging` | 禁用 CrewAI 的 rich 输出，通过 intercept 模式接入 Loguru |

```python
# 日志统一方案
import logging
from loguru import logger

class InterceptHandler(logging.Handler):
    """将标准 logging 重定向到 Loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

# 在适配器初始化时安装
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
```

### 5.4 时区统一

| 参与方 | 当前时区 | 冲突风险 | 解决措施 |
|-------|---------|---------|---------|
| Open-AwA | UTC（通过 `datetime.now(timezone.utc)`） | 无 | - |
| LlamaIndex | 无时间依赖 | 低 | 在适配器中统一使用 UTC |
| CrewAI | `datetime.now()`（无时区） | 中 | 在 CrewAI 适配器中注入 `timezone` 参数 |

**统一方案：**

```python
# 在适配器中强制使用 UTC
from datetime import datetime, timezone

def utc_now() -> datetime:
    """统一获取当前 UTC 时间"""
    return datetime.now(timezone.utc)

# CrewAI 的 LLM 调用中透传时区信息
crew = Crew(
    agents=agents,
    tasks=tasks,
    process=Process.sequential,
    # 不依赖 CrewAI 的时间处理，所有时间戳在适配器层统一处理
)
```

### 5.5 序列化协议兼容

| 序列化场景 | Open-AwA 格式 | 候选库格式 | 转换策略 |
|-----------|--------------|-----------|---------|
| JSON 序列化 | `json.dumps`（Python 默认） | 同上 | 兼容 |
| Pydantic 模型 | `model.model_dump()` | 无 | LlamaIndex/CrewAI 使用字典，适配器中转换 |
| SSE 事件流 | `data: {json}\n\n` | CrewAI 输出需包装 | 在适配器中将 CrewAI 结果包装为 SSE 格式 |
| SQLAlchemy ORM | `declarative_base` | 无 | 候选库不直接操作数据库 |

```python
# 序列化转换器示例
def crewai_result_to_openawa_format(crew_result: CrewOutput) -> Dict[str, Any]:
    """将 CrewAI 的执行结果转换为 Open-AwA 统一响应格式"""
    return {
        "status": "completed",
        "response": str(crew_result.raw),
        "results": [
            {
                "type": "agent_execution",
                "agent": task_result.agent,
                "output": str(task_result.output),
            }
            for task_result in crew_result.tasks_output
        ],
        "usage": {
            "total_tokens": crew_result.token_usage.total_tokens,
        },
    }
```

---

## 6. 集成方案对比

### 6.1 综合对比表

| 维度 | LlamaIndex | CrewAI | Agno | LangChain（对照） |
|------|-----------|--------|------|-----------------|
| **集成复杂度** | 低 | 低 | 低 | 中 |
| **代码侵入性** | 低（防腐层隔离） | 低（防腐层隔离） | 低（防腐层隔离） | 中（需大量适配） |
| **已有依赖冲突** | 无（仅新增 ChromaDB 兼容模式） | 无 | 无 | 存在（liteLLM 重复） |
| **安全风险** | 低（无 CVE） | 低（无 CVE） | 低（无 CVE） | 高（多个 CVE） |
| **许可证风险** | 低（MIT） | 低（MIT） | 低（Apache-2.0） | 低（MIT） |
| **与现有 RAG 系统集成度** | 高（直接增强） | 低（不涉及 RAG） | 中 | 中 |
| **与现有 Agent 系统集成度** | 低（不涉及 Agent） | 高（补充多 Agent 编排） | 高（替换 Agent 运行时） | 高（但需大量适配） |
| **学习成本** | 低 | 中 | 中 | 高 |
| **维护成本** | 低 | 低 | 低（但生态较新） | 中高 |
| **性能影响** | 正面（检索更快） | 正面（并行执行） | 正面（10,000x 更快） | 负面（框架开销） |
| **推荐度** | 强烈推荐 | 推荐 | 有条件推荐 | 不推荐 |

### 6.2 集成复杂度评分

| 集成子任务 | LlamaIndex | CrewAI | Agno | 说明 |
|-----------|:----------:|:------:|:----:|------|
| 依赖安装 | 1 天 | 0.5 天 | 0.5 天 | `pip install` |
| 防腐层开发 | 3 天 | 3 天 | 3 天 | 含接口定义 + 适配器实现 |
| 数据迁移 | 2 天 | 0 天 | 0 天 | 仅 LlamaIndex 需要 |
| 配置合并 | 0.5 天 | 0.5 天 | 0.5 天 | 统一在 settings.py |
| 测试覆盖 | 3 天 | 3 天 | 3 天 | 单元 + 集成测试 |
| 文档更新 | 1 天 | 1 天 | 1 天 | 配置说明 + API 文档 |
| **总计** | **10.5 天** | **8 天** | **8 天** | 并行开发可缩短 |

### 6.3 推荐集成路径

```
短期（v1.x，当前迭代）
  +-- LlamaIndex 集成（高优先级）
  |    增强现有 RAG 能力，替换自定义向量检索
  |    @适配器: RAGAdapter -> LlamaIndexAdapter
  |
  +-- CrewAI 集成（中优先级）
       补充多 Agent 编排能力
       @适配器: AgentOrchestrator -> CrewAIAdapter

中期（v2.x，下个大版本）
  +-- Agno 性能优化（依据需求）
       当 CrewAI 编排出现性能瓶颈时引入
       @适配器: AgentOrchestrator -> AgnoAdapter（可替换 CrewAIAdapter）

长期（v3.x，未来规划）
  +-- 抽象化统一
       RAGAdapter + AgentOrchestrator 成为平台标准接口
       支持通过配置切换不同后端实现
```

### 6.4 风险与缓解措施

| 风险 | 等级 | 发生概率 | 影响 | 缓解措施 |
|------|:----:|:--------:|:----:|---------|
| LlamaIndex API 变更导致适配器需更新 | 中 | 中 | 中 | 防腐层隔离，更新仅影响适配器 |
| CrewAI v1.x 尚在快速迭代，API 不稳定 | 中 | 高 | 中 | 锁定次要版本，定期评估升级 |
| Agno 项目较新，社区支持不足 | 低 | 中 | 低 | 仅作为备选方案 |
| 集成后性能不及预期 | 低 | 低 | 低 | 通过适配器开关回退到原有实现 |
| 数据迁移过程中数据丢失 | 低 | 低 | 高 | 保留原数据库备份，迁移脚本可回滚 |

---

> 本方案基于 2026 年 4 月 24 日的项目代码和候选库版本编制，建议在实际集成前重新确认候选库的最新版本和 API 变更。
