"""
后端接口数据模型定义模块，负责声明请求体、响应体与接口传输结构。
这里的字段定义会直接影响输入校验和输出序列化行为。
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Any, Dict
from datetime import datetime


class UserBase(BaseModel):
    """用户基础字段：用户名。"""
    username: str


class UserCreate(UserBase):
    """用户注册请求体：用户名 + 密码（8-128 字符）。"""
    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    """
    用户响应模型，包含完整的用户信息和画像数据。
    """
    id: str
    role: str
    avatar_url: Optional[str] = None
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    profile_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT 认证令牌响应：包含 access_token、token_type 和 csrf_token。"""
    access_token: str
    token_type: str
    csrf_token: str


class TokenData(BaseModel):
    """从 JWT payload 中提取的令牌数据，供 Depends 依赖注入使用。"""
    username: Optional[str] = None


class AttachmentItem(BaseModel):
    """
    多模态附件项，包含文件类型、base64 数据和 MIME 类型。
    """
    type: str = Field(..., description="附件类型：image/audio/video")
    data: str = Field(..., max_length=14_000_000, description="base64 编码的文件内容（最大约10MB）")
    mime_type: str = Field(..., description="MIME 类型，如 image/png")
    file_name: Optional[str] = None


class ChatContinuation(BaseModel):
    """
    continuation 请求载荷，用于携带子代理聚合结果继续同一轮任务。
    """
    source: str = Field(..., description="continuation 来源，当前固定为 subagent")
    aggregated_context: str = Field(..., max_length=200000, description="子代理输出聚合文本")
    merge_with_last_assistant: Optional[bool] = Field(True, description="是否在持久化时并入上一条 assistant 消息")


class ChatMessage(BaseModel):
    """
    聊天消息请求体，支持文本、多模态附件和思考模式参数。
    """
    message: str = Field(..., max_length=32000, description="用户消息内容")
    session_id: Optional[str] = "default"
    provider: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[str] = "stream"
    attachments: Optional[List[AttachmentItem]] = None
    thinking_enabled: Optional[bool] = None
    thinking_depth: Optional[int] = Field(None, ge=0, le=5, description="思考深度 0-5")
    max_tool_call_rounds: Optional[int] = Field(None, ge=1, le=50000, description="单次对话允许的最大工具回环轮次")
    continuation: Optional[ChatContinuation] = None


class ChatResponse(BaseModel):
    """
    聊天接口响应模型，包含回复内容、推理过程及错误信息。
    """
    status: str
    response: str
    reasoning_content: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


class SkillBase(BaseModel):
    """技能基础字段模型。"""
    name: str
    version: Optional[str] = None
    description: Optional[str] = None


class SkillCreate(SkillBase):
    """创建技能请求体。"""
    config: str


class SkillResponse(SkillBase):
    """技能查询响应模型，包含完整技能信息。"""
    id: str
    config: Optional[Dict[str, Any]] = None
    enabled: bool
    installed_at: datetime
    
    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class PluginBase(BaseModel):
    """插件基础字段模型。"""
    name: str
    version: Optional[str] = None


class PluginCreate(PluginBase):
    """创建插件请求体。"""
    config: Dict[str, Any] = Field(default_factory=dict)


class PluginImportUrlRequest(BaseModel):
    """
    封装远程 URL 导入插件所需请求参数。
    """

    source_url: str
    timeout_seconds: Optional[int] = 30


class PluginResponse(PluginBase):
    """
    插件响应模型，包含数据库记录字段和可选的运行时状态字段。
    """
    id: str
    enabled: bool
    installed_at: datetime
    runtime_loaded: Optional[bool] = None
    runtime_state: Optional[str] = None
    # 插件分类，builtin 表示系统内置插件
    category: Optional[str] = None
    # 插件作者
    author: Optional[str] = None
    # 插件来源
    source: Optional[str] = None
    # 是否为不可卸载的内置插件（True 表示受 403 保护，不可卸载/禁用）
    is_uninstallable: bool = False

    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class MemoryBase(BaseModel):
    """记忆基础字段模型。"""
    content: str


class ShortTermMemoryCreate(MemoryBase):
    """创建短期记忆请求体。"""
    session_id: str
    role: str


class LongTermMemoryCreate(MemoryBase):
    """创建长期记忆请求体。"""
    importance: Optional[float] = 0.5
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    source_type: Optional[str] = Field(default="user_input", description="记忆来源类型")


class ShortTermMemoryResponse(MemoryBase):
    """短期记忆查询响应模型。"""
    id: int
    session_id: str
    role: str
    timestamp: datetime
    
    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class LongTermMemoryResponse(MemoryBase):
    """长期记忆查询响应模型。"""
    id: int
    importance: float
    created_at: datetime
    access_count: int
    last_access: datetime
    confidence: float
    quality_score: float
    archive_status: str
    memory_metadata: Dict[str, Any]
    
    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class MemoryVectorSearchRequest(BaseModel):
    """
    向量检索请求模型。
    """
    query: str = Field(..., description="搜索文本")
    limit: int = Field(default=10, ge=1, le=50)
    include_archived: bool = Field(default=False)
    keyword_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.65, ge=0.0, le=1.0)


class MemoryArchiveRequest(BaseModel):
    """
    记忆归档请求模型。
    """
    older_than_days: int = Field(default=30, ge=1, le=3650)
    importance_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    include_low_quality: bool = Field(default=True)


class MemoryQualityResponse(BaseModel):
    """
    记忆质量评估响应模型。
    """
    memory_id: int
    confidence: float
    quality_score: float
    archive_status: str
    importance: float
    access_count: int


class MemoryStatsResponse(BaseModel):
    """
    记忆统计响应模型。
    """
    total_memories: int
    active_memories: int
    archived_memories: int
    average_confidence: float
    average_quality_score: float
    total_access_count: int
    working_memory_count: int
    vector_store_count: int
    embedding_provider: str


class ConversationSessionCreate(BaseModel):
    """
    会话创建请求模型。
    """
    title: Optional[str] = Field(default=None, max_length=200)
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=100)


class ConversationSessionRenameRequest(BaseModel):
    """
    会话重命名请求模型。
    """
    title: str = Field(..., min_length=1, max_length=200)


class ConversationSessionBatchDeleteRequest(BaseModel):
    """
    会话批量删除请求模型。
    """
    session_ids: List[str] = Field(..., min_length=1)
    retention_days: int = Field(default=30, ge=1, le=3650)


class ConversationSessionResponse(BaseModel):
    """
    会话响应模型。
    """
    session_id: str
    user_id: str
    title: str
    summary: str
    last_message_preview: str
    last_message_role: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    restored_at: Optional[datetime] = None
    purge_after: Optional[datetime] = None
    conversation_metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ConversationSessionListResponse(BaseModel):
    """
    会话列表响应模型。
    """
    items: List[ConversationSessionResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class WorkflowBase(BaseModel):
    """
    工作流基础模型。
    """
    name: str
    description: Optional[str] = ""
    format: str = "yaml"


class WorkflowCreate(WorkflowBase):
    """
    工作流创建请求模型。
    """
    definition: Dict[str, Any] | str
    enabled: bool = True


class WorkflowUpdate(BaseModel):
    """
    工作流更新请求模型。
    """
    name: Optional[str] = None
    description: Optional[str] = None
    format: Optional[str] = None
    definition: Optional[Dict[str, Any] | str] = None
    enabled: Optional[bool] = None


class WorkflowResponse(WorkflowBase):
    """
    工作流响应模型。
    """
    id: int
    definition: Dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecutionRequest(BaseModel):
    """
    工作流执行请求模型。
    """
    workflow_id: Optional[int] = None
    workflow_name: Optional[str] = None
    definition: Optional[Dict[str, Any] | str] = None
    format: Optional[str] = "yaml"
    input_context: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResponse(BaseModel):
    """
    工作流执行记录响应模型。
    """
    id: int
    workflow_id: Optional[int]
    workflow_name: Optional[str]
    user_id: Optional[str]
    status: str
    input_payload: Dict[str, Any]
    output_payload: Dict[str, Any]
    error_message: Optional[str] = None
    execution_metadata: Dict[str, Any]
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScheduledTaskBase(BaseModel):
    """
    定时任务基础模型，支持单次和每日重复任务，以及AI提示词/插件命令两种任务类型。
    """
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(default="")
    scheduled_at: datetime
    provider: Optional[str] = None
    model: Optional[str] = None
    is_daily: Optional[bool] = False
    cron_expression: Optional[str] = None
    weekdays: Optional[str] = None
    daily_time: Optional[str] = None
    task_type: Optional[str] = "ai_prompt"
    plugin_name: Optional[str] = None
    command_name: Optional[str] = None
    command_params: Dict[str, Any] = Field(default_factory=dict)


class ScheduledTaskCreate(ScheduledTaskBase):
    """
    定时任务创建请求模型。
    """
    pass


class ScheduledTaskUpdate(BaseModel):
    """
    定时任务更新请求模型。
    """
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    prompt: Optional[str] = Field(default=None, min_length=1)
    scheduled_at: Optional[datetime] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    is_daily: Optional[bool] = None
    cron_expression: Optional[str] = None
    weekdays: Optional[str] = None
    daily_time: Optional[str] = None
    task_type: Optional[str] = None
    plugin_name: Optional[str] = None
    command_name: Optional[str] = None
    command_params: Optional[Dict[str, Any]] = None


class ScheduledTaskResponse(ScheduledTaskBase):
    """
    定时任务响应模型。
    """
    id: int
    user_id: str
    status: str
    last_error_message: Optional[str] = None
    task_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    next_execution_at: Optional[str] = None

    class Config:
        from_attributes = True


class PluginCommandInfo(BaseModel):
    """
    插件命令信息，用于前端展示可选命令列表。
    """
    plugin_name: str
    plugin_version: str
    plugin_description: str
    command_name: str
    command_description: str
    command_method: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ScheduledTaskExecutionResponse(BaseModel):
    """
    定时任务执行记录响应模型。
    """
    id: int
    task_id: int
    user_id: str
    task_title: str
    prompt: str
    scheduled_for: datetime
    status: str
    response: Optional[str] = None
    error_message: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    request_id: Optional[str] = None
    execution_metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PromptConfigBase(BaseModel):
    """提示词配置基础字段模型。"""
    name: str
    content: str
    variables: Optional[str] = None


class PromptConfigCreate(PromptConfigBase):
    """创建提示词配置请求体。"""
    pass


class PromptConfigUpdate(BaseModel):
    """更新提示词配置请求体。"""
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    is_active: Optional[bool] = None


class PromptConfigResponse(PromptConfigBase):
    """提示词配置查询响应模型。"""
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class BehaviorStats(BaseModel):
    """行为统计数据模型。"""
    total_interactions: int
    total_tools_used: int
    total_errors: int
    top_tools: List[Any]
    top_intents: List[Any]
    average_response_time: float
    chart_data: Optional[List[Any]] = None


class ConfirmationRequest(BaseModel):
    """确认请求体。"""
    confirmed: bool
    step: Optional[Dict[str, Any]] = None


class ExperienceBase(BaseModel):
    """经验基础字段模型。"""
    experience_type: str = Field(..., description="经验类型")
    title: str = Field(..., max_length=200, description="经验标题")
    content: str = Field(..., description="经验内容")
    trigger_conditions: str = Field(..., description="触发条件")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    source_task: Optional[str] = Field(default="general", description="来源任务")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")


class ExperienceCreate(ExperienceBase):
    """创建经验请求体。"""
    pass


class ExperienceUpdate(BaseModel):
    """更新经验请求体。"""
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    trigger_conditions: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None


class ExperienceResponse(ExperienceBase):
    """经验查询响应模型。"""
    id: int
    usage_count: int = 0
    success_count: int = 0
    created_at: datetime
    last_access: datetime
    
    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class ExperienceSearchParams(BaseModel):
    """经验搜索参数模型。"""
    query: Optional[str] = None
    experience_type: Optional[str] = None
    min_confidence: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    source_task: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ExperienceExtractionRequest(BaseModel):
    """经验提取请求体。"""
    session_id: str
    user_goal: str
    execution_steps: List[Dict[str, Any]]
    final_result: str
    status: str = Field(..., description="success or failure")


class ExperienceStatsResponse(BaseModel):
    """经验统计响应模型。"""
    total_experiences: int
    type_distribution: Dict[str, int]
    avg_confidence: float
    avg_success_rate: float
    total_usage: int
    total_success: int
    top_experiences: List[Dict[str, Any]]


class SkillUpdate(BaseModel):
    """更新技能请求体。"""
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    config: Optional[str] = None
    enabled: Optional[bool] = None


class SkillExecute(BaseModel):
    """技能执行请求体，指定执行参数。"""
    inputs: Dict[str, Any] = Field(default_factory=dict, description="技能输入参数")
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")


class SkillConfigResponse(BaseModel):
    """技能配置响应模型。"""
    skill_id: str
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    config: Dict[str, Any]
    enabled: bool
    installed_at: datetime

    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class SkillValidationResult(BaseModel):
    """技能校验结果模型。"""
    valid: bool
    errors: List[str]
    warnings: List[str]
    skill_name: Optional[str] = None
    version: Optional[str] = None


class SkillValidationRequest(BaseModel):
    """技能校验请求体。"""
    yaml_content: str = Field(..., description="YAML 格式的技能配置")


class PluginUpdate(BaseModel):
    """更新插件请求体。"""
    name: Optional[str] = None
    version: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class PluginExecute(BaseModel):
    """插件执行请求体。"""
    method: str = Field(..., description="要执行的插件方法")
    params: Dict[str, Any] = Field(default_factory=dict, description="方法参数")


class PluginPermissionUpdateRequest(BaseModel):
    """插件权限更新请求体。"""
    permissions: List[str] = Field(default_factory=list, description="要授权或撤销的权限列表")


class PluginPermissionStatus(BaseModel):
    """插件权限状态模型。"""
    plugin_id: str
    plugin_name: str
    requested_permissions: List[str]
    granted_permissions: List[str]
    missing_permissions: List[str]


class PluginPermissionUpdateResponse(PluginPermissionStatus):
    """插件权限更新响应模型。"""
    message: str


class PluginToolsResponse(BaseModel):
    """插件工具列表响应模型。"""
    plugin_id: str
    plugin_name: str
    tools: List[Dict[str, Any]]


class PluginValidationResult(BaseModel):
    """插件校验结果模型。"""
    valid: bool
    errors: List[str]
    warnings: List[str]


class PluginValidationRequest(BaseModel):
    """插件校验请求体。"""
    yaml_content: str = Field(..., description="YAML 格式的插件配置")


class PluginDiscoveryResult(BaseModel):
    """插件发现结果模型。"""
    discovered: List[Dict[str, Any]]
    total_count: int


class RolloutConfigSchema(BaseModel):
    """灰度发布配置模型。"""
    enabled: bool = False
    strategy: str = Field(default="percentage", description="percentage / user_list / region")
    percentage: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    user_list: Optional[List[str]] = Field(default_factory=list)
    region: Optional[List[str]] = Field(default_factory=list)


class HotUpdateRequest(BaseModel):
    """热更新请求体。"""
    rollout_config: Optional[RolloutConfigSchema] = None
    strategy: str = Field(default="gray", description="gray / immediate / force")


class HotUpdateResponse(BaseModel):
    """热更新响应模型。"""
    success: bool
    plugin_name: str
    strategy: str
    new_version: Optional[str] = None
    standby_ready: bool = False
    rollout_config: Optional[Dict[str, Any]] = None
    active_release_id: Optional[str] = None
    standby_release_id: Optional[str] = None
    rolled_back: bool = False
    error: Optional[str] = None
    hot_update_status: Optional[Dict[str, Any]] = None


class RollbackRequest(BaseModel):
    """回滚请求体。"""
    snapshot_id: Optional[str] = Field(default=None, description="要恢复的快照ID，不填则使用最新快照")


class RollbackResponse(BaseModel):
    """回滚响应模型。"""
    success: bool
    plugin_name: str
    rolled_back_to: Optional[str] = None
    snapshot_id: Optional[str] = None
    error: Optional[str] = None


class PluginLogEntry(BaseModel):
    """插件日志条目模型。"""
    timestamp: str
    level: str
    message: str
    plugin_id: str
    extra: Dict[str, Any] = Field(default_factory=dict)


class PluginLogsResponse(BaseModel):
    """插件日志查询响应模型。"""
    plugin_id: str
    plugin_name: str
    level_filter: Optional[str]
    total: int
    entries: List[PluginLogEntry]


class PluginLogLevelUpdate(BaseModel):
    """插件日志级别更新请求体。"""
    level: str = Field(..., description="日志级别: DEBUG / INFO / WARNING / ERROR / CRITICAL")


class PluginLogLevelResponse(BaseModel):
    """插件日志级别响应模型。"""
    plugin_id: str
    plugin_name: str
    level: str


class ProviderConfigurationBase(BaseModel):
    """模型供应商配置基础字段模型。"""
    provider: str
    model: str
    max_tokens: Optional[int] = None


class ProviderConfigurationCreate(ProviderConfigurationBase):
    """创建供应商配置请求体。"""
    pass


class ProviderConfigurationUpdate(BaseModel):
    """更新供应商配置请求体。"""
    max_tokens: Optional[int] = None


class ProviderConfigurationResponse(ProviderConfigurationBase):
    """供应商配置查询响应模型。"""
    id: int

    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


# -------- MCP 相关数据模型 --------

class MCPServerCreate(BaseModel):
    """MCP Server 创建请求"""
    name: str = Field(..., description="服务器名称")
    command: Optional[str] = Field(None, description="Stdio 模式启动命令")
    args: Optional[List[str]] = Field(default=None, description="启动命令参数")
    env: Optional[Dict[str, str]] = Field(default=None, description="环境变量")
    transport_type: str = Field(default="stdio", description="传输类型: stdio / sse")
    url: Optional[str] = Field(None, description="SSE 模式服务器地址")


class MCPServerResponse(BaseModel):
    """MCP Server 状态响应"""
    id: str = Field(..., description="服务器 ID")
    name: str = Field(..., description="服务器名称")
    transport_type: str = Field(..., description="传输类型")
    status: str = Field(..., description="连接状态")
    tools_count: int = Field(default=0, description="工具数量")


class MCPToolCallCreate(BaseModel):
    """MCP 工具调用请求"""
    server_id: str = Field(..., description="目标服务器 ID")
    tool_name: str = Field(..., description="工具名称")
    arguments: Optional[Dict[str, Any]] = Field(default=None, description="调用参数")


class MCPToolCallResponse(BaseModel):
    """MCP 工具调用响应"""
    result: Any = Field(None, description="调用结果")
    is_error: bool = Field(False, description="是否为错误响应")


# -------- 插件市场相关数据模型 --------

class MarketplacePluginResponse(BaseModel):
    """插件市场单个插件的响应模型"""
    id: str = Field(..., description="插件唯一标识")
    name: str = Field(..., description="插件名称")
    description: str = Field(default="", description="插件描述")
    author: str = Field(default="", description="作者")
    version: str = Field(default="1.0.0", description="版本号")
    category: str = Field(default="other", description="插件分类")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    download_url: str = Field(default="", description="下载地址")
    icon: str = Field(default="", description="图标地址")
    install_count: int = Field(default=0, description="安装次数")


class MarketplaceSearchResponse(BaseModel):
    """插件市场搜索/列表响应模型"""
    plugins: List[MarketplacePluginResponse] = Field(default_factory=list, description="插件列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=12, description="每页数量")


# -------- 插件市场版本管理数据模型 --------

class PluginVersionResponse(BaseModel):
    """插件版本响应模型"""
    id: int = Field(..., description="版本记录 ID")
    plugin_id: str = Field(..., description="插件 ID")
    version: str = Field(..., description="版本号")
    changelog: str = Field(default="", description="变更日志")
    download_url: str = Field(default="", description="下载地址")
    sha256_checksum: str = Field(default="", description="SHA256 校验和")
    min_platform_version: Optional[str] = Field(None, description="最低平台版本")
    max_platform_version: Optional[str] = Field(None, description="最高平台版本")
    is_published: bool = Field(default=True, description="是否已发布")
    published_at: datetime = Field(..., description="发布时间")
    release_channel: str = Field(default="stable", description="发布通道")

    model_config = {"from_attributes": True}


class PluginVersionListResponse(BaseModel):
    """插件版本列表响应模型"""
    plugin_id: str = Field(..., description="插件 ID")
    versions: List[PluginVersionResponse] = Field(default_factory=list, description="版本列表")
    total: int = Field(default=0, description="版本总数")


class PluginInstallWithVersionRequest(BaseModel):
    """带版本号的插件安装请求"""
    version: Optional[str] = Field(None, description="指定版本号，为空则安装最新稳定版")


class PluginUpgradeRequest(BaseModel):
    """插件升级请求"""
    target_version: str = Field(..., description="目标版本号")


class PluginUpgradeResponse(BaseModel):
    """插件升级响应"""
    success: bool = Field(..., description="是否成功")
    plugin_id: str = Field(..., description="插件 ID")
    previous_version: str = Field(..., description="原版本")
    current_version: str = Field(..., description="当前版本")
    message: str = Field(default="", description="附加消息")


class PluginUpdateCheckResponse(BaseModel):
    """插件更新检查响应"""
    has_update: bool = Field(..., description="是否有可用更新")
    current_version: str = Field(..., description="当前版本")
    latest_version: Optional[str] = Field(None, description="最新版本")
    latest_changelog: Optional[str] = Field(None, description="最新版本变更日志")


# -------- 插件市场社区功能数据模型 --------

class PluginRatingCreate(BaseModel):
    """插件评分创建请求"""
    score: int = Field(..., ge=1, le=5, description="评分（1-5 星）")


class PluginRatingSummaryResponse(BaseModel):
    """插件评分汇总响应"""
    plugin_id: str = Field(..., description="插件 ID")
    average_score: float = Field(default=0.0, description="平均分")
    total_count: int = Field(default=0, description="评分总数")
    distribution: Dict[int, int] = Field(default_factory=dict, description="评分分布（1-5 星各数量）")
    user_score: Optional[int] = Field(None, description="当前用户评分")


class PluginReviewCreate(BaseModel):
    """插件评论创建请求"""
    content: str = Field(..., min_length=1, max_length=2000, description="评论内容")
    rating: Optional[int] = Field(None, ge=1, le=5, description="附带评分（1-5 星，可选）")


class PluginReviewUpdate(BaseModel):
    """插件评论更新请求"""
    content: Optional[str] = Field(None, min_length=1, max_length=2000, description="评论内容")
    rating: Optional[int] = Field(None, ge=1, le=5, description="附带评分")


class PluginReviewResponse(BaseModel):
    """插件评论响应模型"""
    id: int = Field(..., description="评论 ID")
    plugin_id: str = Field(..., description="插件 ID")
    user_id: str = Field(..., description="用户 ID")
    username: str = Field(default="", description="用户名")
    content: str = Field(..., description="评论内容")
    rating: Optional[int] = Field(None, description="附带评分")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = {"from_attributes": True}


class PluginReviewListResponse(BaseModel):
    """插件评论列表响应"""
    plugin_id: str = Field(..., description="插件 ID")
    reviews: List[PluginReviewResponse] = Field(default_factory=list, description="评论列表")
    total: int = Field(default=0, description="评论总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")


class PluginDownloadResponse(BaseModel):
    """插件下载响应"""
    success: bool = Field(..., description="是否成功")
    plugin_id: str = Field(..., description="插件 ID")
    version: str = Field(..., description="下载版本")
    sha256: str = Field(default="", description="实际 SHA256 校验和")
    message: str = Field(default="", description="附加消息")


# -------- 安全与 RBAC 相关数据模型 --------

class RoleResponse(BaseModel):
    """角色信息响应模型"""
    name: str = Field(..., description="角色名称")
    display_name: Optional[str] = Field(None, description="角色显示名称")
    permissions: List[str] = Field(default_factory=list, description="权限列表")


class UserRoleResponse(BaseModel):
    """用户角色信息响应模型"""
    user_id: str = Field(..., description="用户 ID")
    role_name: str = Field(..., description="角色名称")
    assigned_at: Optional[datetime] = Field(None, description="分配时间")

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    """用户角色更新请求模型"""
    role_name: str = Field(..., description="目标角色名称")


class PermissionCheckRequest(BaseModel):
    """权限检查请求模型"""
    user_id: str = Field(..., description="用户 ID")
    permission: str = Field(..., description="权限标识，如 chat:send")


class PermissionCheckResponse(BaseModel):
    """权限检查响应模型"""
    allowed: bool = Field(..., description="是否允许")
    role: str = Field(..., description="用户当前角色")
    permission: str = Field(..., description="检查的权限")


# -------- P2 安全增强：细粒度权限与主动防御 --------


class CustomRoleCreate(BaseModel):
    """自定义角色创建请求"""
    name: str = Field(..., min_length=1, max_length=50, description="角色名称")
    display_name: str = Field(default="", max_length=100, description="显示名称")
    description: str = Field(default="", max_length=500, description="角色描述")
    permissions: List[str] = Field(..., min_length=1, description="权限列表，格式 resource:action")


class CustomRoleUpdate(BaseModel):
    """自定义角色更新请求"""
    display_name: Optional[str] = Field(None, max_length=100, description="显示名称")
    description: Optional[str] = Field(None, max_length=500, description="角色描述")
    permissions: Optional[List[str]] = Field(None, min_length=1, description="权限列表")


class CustomRoleResponse(BaseModel):
    """自定义角色响应模型"""
    id: int = Field(..., description="角色 ID")
    name: str = Field(..., description="角色名称")
    display_name: str = Field(default="", description="显示名称")
    description: str = Field(default="", description="角色描述")
    permissions: List[str] = Field(default_factory=list, description="权限列表")
    created_by: Optional[str] = Field(None, description="创建者")
    is_system: bool = Field(default=False, description="是否系统角色")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")


class FineGrainedPermissionCheckRequest(BaseModel):
    """细粒度权限检查请求"""
    user_id: str = Field(..., description="用户 ID")
    permission: str = Field(..., description="权限标识，如 plugin:install")


class FineGrainedPermissionCheckResponse(BaseModel):
    """细粒度权限检查响应"""
    allowed: bool = Field(..., description="是否允许")
    permission: str = Field(..., description="检查的权限")


class IpAccessEntryCreate(BaseModel):
    """IP 访问条目创建请求"""
    ip_cidr: str = Field(..., description="IP 地址或 CIDR 网段")
    list_type: str = Field(..., description="whitelist 或 blacklist")
    reason: str = Field(default="", max_length=500, description="添加原因")
    expires_at: Optional[datetime] = Field(None, description="过期时间，None 表示永不过期")


class IpAccessEntryResponse(BaseModel):
    """IP 访问条目响应模型"""
    id: int = Field(..., description="条目 ID")
    ip_cidr: str = Field(..., description="IP 地址或 CIDR 网段")
    list_type: str = Field(..., description="列表类型")
    reason: str = Field(default="", description="添加原因")
    created_by: Optional[str] = Field(None, description="创建者")
    is_active: bool = Field(default=True, description="是否活跃")
    expires_at: Optional[str] = Field(None, description="过期时间 ISO 格式")
    created_at: Optional[str] = Field(None, description="创建时间 ISO 格式")


class IpAccessCheckRequest(BaseModel):
    """IP 访问检查请求"""
    ip_address: str = Field(..., description="待检查的 IP 地址")


class IpAccessCheckResponse(BaseModel):
    """IP 访问检查响应"""
    allowed: bool = Field(..., description="是否允许")
    reason: str = Field(default="", description="决策原因")
    matched_list: str = Field(default="none", description="命中的列表类型")


class AnomalyEventResponse(BaseModel):
    """异常事件响应模型"""
    id: int = Field(..., description="事件 ID")
    event_type: Literal["rate_burst", "repeated_failure", "suspicious_pattern"] = Field(
        ..., description="事件类型"
    )
    user_id: Optional[str] = Field(None, description="用户 ID")
    ip_address: Optional[str] = Field(None, description="IP 地址")
    trigger_detail: str = Field(default="", description="触发阈值描述")
    observed_value: str = Field(default="", description="实际观测值")
    action_taken: Literal["warn", "throttle", "block"] = Field(
        default="warn", description="处置动作"
    )
    is_resolved: bool = Field(default=False, description="是否已解决")
    created_at: Optional[str] = Field(None, description="创建时间 ISO 格式")
    resolved_at: Optional[str] = Field(None, description="解决时间 ISO 格式")


class CsrfTokenGenerateRequest(BaseModel):
    """CSRF token 生成请求"""
    session_id: Optional[str] = Field(None, max_length=64, description="会话 ID")
    ttl_hours: int = Field(default=24, ge=1, le=168, description="有效期（小时）")


class CsrfTokenResponse(BaseModel):
    """CSRF token 响应模型"""
    token: str = Field(..., description="token 字符串")
    expires_at: str = Field(..., description="过期时间 ISO 格式")


class CsrfTokenValidateRequest(BaseModel):
    """CSRF token 校验请求"""
    token: str = Field(..., description="待校验的 token")
    consume: bool = Field(default=True, description="是否一次性消费")


class CsrfTokenValidateResponse(BaseModel):
    """CSRF token 校验响应"""
    valid: bool = Field(..., description="是否有效")
    reason: str = Field(default="", description="校验原因")


class CsrfTokenRotateRequest(BaseModel):
    """CSRF token 轮换请求"""
    old_token: str = Field(..., description="待轮换的旧 token")
    session_id: Optional[str] = Field(None, max_length=64, description="会话 ID")
    ttl_hours: int = Field(default=24, ge=1, le=168, description="新 token 有效期（小时）")


class UserRateLimitStatsResponse(BaseModel):
    """用户速率限制统计响应"""
    user_id: str = Field(..., description="用户 ID")
    current_count: int = Field(..., description="当前窗口请求数")
    max_requests: int = Field(..., description="窗口内最大请求数")
    window_seconds: int = Field(..., description="窗口大小（秒）")


# -------- P3 Chain-of-Thought 推理审计 --------


class ComplexityAssessRequest(BaseModel):
    """复杂度评估请求"""
    user_input: str = Field(..., min_length=1, max_length=10000, description="用户输入文本")


class ComplexityAssessResponse(BaseModel):
    """复杂度评估响应"""
    complexity: str = Field(..., description="复杂度等级: simple/moderate/complex")
    thinking_depth: int = Field(..., ge=0, le=5, description="推荐推理深度")
    score: int = Field(..., ge=0, le=100, description="复杂度评分")
    reasons: List[str] = Field(default_factory=list, description="评估依据")


class ReasoningAuditResponse(BaseModel):
    """推理审计记录响应模型"""
    id: int = Field(..., description="审计记录 ID")
    session_id: str = Field(..., description="会话 ID")
    user_id: Optional[str] = Field(None, description="用户 ID")
    provider: str = Field(default="", description="模型提供商")
    model: str = Field(default="", description="模型名称")
    thinking_depth: int = Field(default=0, description="推理深度")
    complexity: str = Field(default="simple", description="复杂度等级")
    complexity_score: int = Field(default=0, description="复杂度评分")
    is_user_override: bool = Field(default=False, description="是否用户手动覆盖")
    reasoning_length: int = Field(default=0, description="推理内容长度")
    reasoning_tokens: int = Field(default=0, description="推理 token 数")
    output_tokens: int = Field(default=0, description="输出 token 数")
    input_tokens: int = Field(default=0, description="输入 token 数")
    reasoning_duration_ms: int = Field(default=0, description="推理耗时（毫秒）")
    total_duration_ms: int = Field(default=0, description="总耗时（毫秒）")
    ttft_ms: int = Field(default=0, description="首 token 时间（毫秒）")
    success: bool = Field(default=True, description="是否成功")
    error_message: Optional[str] = Field(None, description="错误信息")
    audit_metadata: Optional[Dict[str, Any]] = Field(None, description="审计元数据")
    created_at: Optional[str] = Field(None, description="创建时间 ISO 格式")


class ReasoningAuditListResponse(BaseModel):
    """推理审计列表响应"""
    audits: List[ReasoningAuditResponse] = Field(default_factory=list, description="审计记录列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")


class ReasoningAuditStatsResponse(BaseModel):
    """推理审计统计响应"""
    total: int = Field(default=0, description="审计总数")
    success_rate: float = Field(default=0.0, description="成功率（百分比）")
    avg_reasoning_tokens: float = Field(default=0.0, description="平均推理 token 数")
    avg_output_tokens: float = Field(default=0.0, description="平均输出 token 数")
    avg_reasoning_duration_ms: float = Field(default=0.0, description="平均推理耗时（毫秒）")
    avg_total_duration_ms: float = Field(default=0.0, description="平均总耗时（毫秒）")
    avg_ttft_ms: float = Field(default=0.0, description="平均首 token 时间（毫秒）")
    complexity_distribution: Dict[str, int] = Field(default_factory=dict, description="复杂度分布")
    depth_distribution: Dict[str, int] = Field(default_factory=dict, description="深度分布")


class ReasoningExportResponse(BaseModel):
    """推理内容导出响应"""
    session_id: str = Field(..., description="会话 ID")
    format: str = Field(default="json", description="导出格式")
    items: List[Dict[str, Any]] = Field(default_factory=list, description="导出项列表")
    total: int = Field(default=0, description="导出项总数")


class AuditLogResponse(BaseModel):
    """审计日志响应模型"""
    id: int = Field(..., description="日志 ID")
    user_id: Optional[str] = Field(None, description="用户 ID")
    action: str = Field(..., description="操作类型")
    resource: Optional[str] = Field(None, description="操作资源")
    result: Optional[str] = Field(None, description="操作结果")
    details: Optional[str] = Field(None, description="操作详情")
    ip_address: Optional[str] = Field(None, description="来源 IP")
    created_at: Optional[datetime] = Field(None, description="创建时间")

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """审计日志列表响应模型"""
    logs: List[AuditLogResponse] = Field(default_factory=list, description="日志列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")


class UserPreferencesUpdate(BaseModel):
    """用户偏好更新请求，增量合并到 profile_data["preferences"] 中。"""
    preferences: Dict[str, Any] = Field(default_factory=dict)


class UserPreferencesResponse(BaseModel):
    """用户偏好响应，包含 preferences 子对象。"""
    preferences: Dict[str, Any]


class UserFeedbackRequest(BaseModel):
    """用户对助手消息的显式反馈请求。"""
    session_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID（前端消息的唯一标识）")
    rating: int = Field(..., ge=-1, le=1, description="评分：1=点赞，-1=点踩，0=取消")
    comment: Optional[str] = Field(default=None, max_length=1000, description="可选反馈备注")


class ChatUndoOperationRequest(BaseModel):
    """撤销 AI 执行的文件操作请求体。"""
    operation_id: str = Field(..., min_length=1, max_length=200, description="待撤销的操作 ID")


# -------- 任务执行（非交互式）--------

class TaskExecuteRequest(BaseModel):
    """非交互式任务执行请求，用于 API 驱动的自主任务。"""
    prompt: str = Field(..., min_length=1, max_length=32000, description="任务提示词")
    provider: Optional[str] = Field(None, description="模型供应商")
    model: Optional[str] = Field(None, description="模型名称")
    session_id: Optional[str] = Field(default=None, description="会话 ID（可选，复用已有会话以保持上下文）")
    timeout_seconds: Optional[int] = Field(default=300, ge=10, le=3600, description="任务超时（秒）")
    webhook_url: Optional[str] = Field(None, description="完成后回调 Webhook URL")
    max_tool_call_rounds: Optional[int] = Field(None, ge=1, le=100, description="最大工具调用轮数")
    thinking_depth: Optional[int] = Field(None, ge=0, le=5, description="思考深度")


class TaskExecuteResponse(BaseModel):
    """非交互式任务执行响应。"""
    status: str = Field(..., description="执行状态：success / failed / timeout")
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    response: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls_count: int = 0
    execution_time_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    error: Optional[str] = None


# -------- 持久化权限 --------

class PermissionReplyRequest(BaseModel):
    """权限请求回复模型"""
    request_id: str = Field(..., description="权限请求 ID")
    reply: Literal["once", "always", "reject"] = Field(..., description="回复类型")
    message: Optional[str] = Field(default=None, description="可选备注")


class SavedPermissionResponse(BaseModel):
    """已保存的持久化权限响应模型"""
    id: str = Field(..., description="权限规则 ID")
    action: str = Field(..., description="操作名称")
    resource: str = Field(..., description="资源标识")
    project_id: str = Field(..., description="项目标识")
    created_at: Optional[datetime] = Field(None, description="创建时间")

    class Config:
        from_attributes = True


class SavedPermissionsListResponse(BaseModel):
    """已保存权限列表响应模型"""
    permissions: list[SavedPermissionResponse] = Field(default_factory=list, description="权限列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=50, description="每页数量")
