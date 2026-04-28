"""
后端接口数据模型定义模块，负责声明请求体、响应体与接口传输结构。
这里的字段定义会直接影响输入校验和输出序列化行为。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime


class UserBase(BaseModel):
    """
    封装与UserBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    username: str


class UserCreate(UserBase):
    """
    封装与UserCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    password: str


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
    """
    封装与Token相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    access_token: str
    token_type: str


class TokenData(BaseModel):
    """
    封装与TokenData相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    username: Optional[str] = None


class AttachmentItem(BaseModel):
    """
    多模态附件项，包含文件类型、base64 数据和 MIME 类型。
    """
    type: str = Field(..., description="附件类型：image/audio/video")
    data: str = Field(..., description="base64 编码的文件内容")
    mime_type: str = Field(..., description="MIME 类型，如 image/png")
    file_name: Optional[str] = None


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
    """
    封装与SkillBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str
    version: Optional[str] = None
    description: Optional[str] = None


class SkillCreate(SkillBase):
    """
    封装与SkillCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    config: str


class SkillResponse(SkillBase):
    """
    封装与SkillResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    id: str
    config: Optional[Dict[str, Any]] = None
    enabled: bool
    installed_at: datetime
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class PluginBase(BaseModel):
    """
    封装与PluginBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str
    version: Optional[str] = None


class PluginCreate(PluginBase):
    """
    封装与PluginCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class MemoryBase(BaseModel):
    """
    封装与MemoryBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    content: str


class ShortTermMemoryCreate(MemoryBase):
    """
    封装与ShortTermMemoryCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    session_id: str
    role: str


class LongTermMemoryCreate(MemoryBase):
    """
    封装与LongTermMemoryCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    importance: Optional[float] = 0.5
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    source_type: Optional[str] = Field(default="user_input", description="记忆来源类型")


class ShortTermMemoryResponse(MemoryBase):
    """
    封装与ShortTermMemoryResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    id: int
    session_id: str
    role: str
    timestamp: datetime
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class LongTermMemoryResponse(MemoryBase):
    """
    封装与LongTermMemoryResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
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
    定时任务基础模型，支持单次和每日重复任务。
    """
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
    scheduled_at: datetime
    provider: Optional[str] = None
    model: Optional[str] = None
    is_daily: Optional[bool] = False
    cron_expression: Optional[str] = None
    weekdays: Optional[str] = None
    daily_time: Optional[str] = None


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
    """
    封装与PromptConfigBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str
    content: str
    variables: Optional[str] = None


class PromptConfigCreate(PromptConfigBase):
    """
    封装与PromptConfigCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    pass


class PromptConfigUpdate(BaseModel):
    """
    封装与PromptConfigUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    is_active: Optional[bool] = None


class PromptConfigResponse(PromptConfigBase):
    """
    封装与PromptConfigResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class BehaviorStats(BaseModel):
    """
    封装与BehaviorStats相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    total_interactions: int
    total_tools_used: int
    total_errors: int
    top_tools: List[Any]
    top_intents: List[Any]
    average_response_time: float
    chart_data: Optional[List[Any]] = None


class ConfirmationRequest(BaseModel):
    """
    封装与ConfirmationRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    confirmed: bool
    step: Optional[Dict[str, Any]] = None


class ExperienceBase(BaseModel):
    """
    封装与ExperienceBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    experience_type: str = Field(..., description="经验类型")
    title: str = Field(..., max_length=200, description="经验标题")
    content: str = Field(..., description="经验内容")
    trigger_conditions: str = Field(..., description="触发条件")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    source_task: Optional[str] = Field(default="general", description="来源任务")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")


class ExperienceCreate(ExperienceBase):
    """
    封装与ExperienceCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    pass


class ExperienceUpdate(BaseModel):
    """
    封装与ExperienceUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    trigger_conditions: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None


class ExperienceResponse(ExperienceBase):
    """
    封装与ExperienceResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    id: int
    usage_count: int = 0
    success_count: int = 0
    created_at: datetime
    last_access: datetime
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class ExperienceSearchParams(BaseModel):
    """
    封装与ExperienceSearchParams相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    query: Optional[str] = None
    experience_type: Optional[str] = None
    min_confidence: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    source_task: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ExperienceExtractionRequest(BaseModel):
    """
    封装与ExperienceExtractionRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    session_id: str
    user_goal: str
    execution_steps: List[Dict[str, Any]]
    final_result: str
    status: str = Field(..., description="success or failure")


class ExperienceStatsResponse(BaseModel):
    """
    封装与ExperienceStatsResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    total_experiences: int
    type_distribution: Dict[str, int]
    avg_confidence: float
    avg_success_rate: float
    total_usage: int
    total_success: int
    top_experiences: List[Dict[str, Any]]


class SkillUpdate(BaseModel):
    """
    封装与SkillUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    config: Optional[str] = None
    enabled: Optional[bool] = None


class SkillExecute(BaseModel):
    """
    封装与SkillExecute相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    inputs: Dict[str, Any] = Field(default_factory=dict, description="技能输入参数")
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")


class SkillConfigResponse(BaseModel):
    """
    封装与SkillConfigResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    skill_id: str
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    config: Dict[str, Any]
    enabled: bool
    installed_at: datetime

    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        from_attributes = True


class SkillValidationResult(BaseModel):
    """
    封装与SkillValidationResult相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    valid: bool
    errors: List[str]
    warnings: List[str]
    skill_name: Optional[str] = None
    version: Optional[str] = None


class SkillValidationRequest(BaseModel):
    """
    封装与SkillValidationRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    yaml_content: str = Field(..., description="YAML 格式的技能配置")


class PluginUpdate(BaseModel):
    """
    封装与PluginUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: Optional[str] = None
    version: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class PluginExecute(BaseModel):
    """
    封装与PluginExecute相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    method: str = Field(..., description="要执行的插件方法")
    params: Dict[str, Any] = Field(default_factory=dict, description="方法参数")


class PluginPermissionUpdateRequest(BaseModel):
    """
    封装与PluginPermissionUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    permissions: List[str] = Field(default_factory=list, description="要授权或撤销的权限列表")


class PluginPermissionStatus(BaseModel):
    """
    封装与PluginPermissionStatus相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    plugin_id: str
    plugin_name: str
    requested_permissions: List[str]
    granted_permissions: List[str]
    missing_permissions: List[str]


class PluginPermissionUpdateResponse(PluginPermissionStatus):
    """
    封装与PluginPermissionUpdateResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    message: str


class PluginToolsResponse(BaseModel):
    """
    封装与PluginToolsResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    plugin_id: str
    plugin_name: str
    tools: List[Dict[str, Any]]


class PluginValidationResult(BaseModel):
    """
    封装与PluginValidationResult相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    valid: bool
    errors: List[str]
    warnings: List[str]


class PluginValidationRequest(BaseModel):
    """
    封装与PluginValidationRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    yaml_content: str = Field(..., description="YAML 格式的插件配置")


class PluginDiscoveryResult(BaseModel):
    """
    封装与PluginDiscoveryResult相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    discovered: List[Dict[str, Any]]
    total_count: int


class RolloutConfigSchema(BaseModel):
    """
    封装与RolloutConfigSchema相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    enabled: bool = False
    strategy: str = Field(default="percentage", description="percentage / user_list / region")
    percentage: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    user_list: Optional[List[str]] = Field(default_factory=list)
    region: Optional[List[str]] = Field(default_factory=list)


class HotUpdateRequest(BaseModel):
    """
    封装与HotUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    rollout_config: Optional[RolloutConfigSchema] = None
    strategy: str = Field(default="gray", description="gray / immediate / force")


class HotUpdateResponse(BaseModel):
    """
    封装与HotUpdateResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
    """
    封装与RollbackRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    snapshot_id: Optional[str] = Field(default=None, description="要恢复的快照ID，不填则使用最新快照")


class RollbackResponse(BaseModel):
    """
    封装与RollbackResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    success: bool
    plugin_name: str
    rolled_back_to: Optional[str] = None
    snapshot_id: Optional[str] = None
    error: Optional[str] = None


class PluginLogEntry(BaseModel):
    """
    封装与PluginLogEntry相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    timestamp: str
    level: str
    message: str
    plugin_id: str
    extra: Dict[str, Any] = Field(default_factory=dict)


class PluginLogsResponse(BaseModel):
    """
    封装与PluginLogsResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    plugin_id: str
    plugin_name: str
    level_filter: Optional[str]
    total: int
    entries: List[PluginLogEntry]


class PluginLogLevelUpdate(BaseModel):
    """
    封装与PluginLogLevelUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    level: str = Field(..., description="日志级别: DEBUG / INFO / WARNING / ERROR / CRITICAL")


class PluginLogLevelResponse(BaseModel):
    """
    封装与PluginLogLevelResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    plugin_id: str
    plugin_name: str
    level: str


class ProviderConfigurationBase(BaseModel):
    """
    封装与ProviderConfigurationBase相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    provider: str
    model: str
    max_tokens: Optional[int] = None


class ProviderConfigurationCreate(ProviderConfigurationBase):
    """
    封装与ProviderConfigurationCreate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    pass


class ProviderConfigurationUpdate(BaseModel):
    """
    封装与ProviderConfigurationUpdate相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    max_tokens: Optional[int] = None


class ProviderConfigurationResponse(ProviderConfigurationBase):
    """
    封装与ProviderConfigurationResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    id: int

    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
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
