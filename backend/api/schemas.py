from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: str
    role: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    status: str
    response: str
    session_id: Optional[str] = None


class SkillBase(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None


class SkillCreate(SkillBase):
    config: str


class SkillResponse(SkillBase):
    id: str
    enabled: bool
    installed_at: datetime
    
    class Config:
        from_attributes = True


class PluginBase(BaseModel):
    name: str
    version: Optional[str] = None


class PluginCreate(PluginBase):
    config: Optional[str] = None


class PluginResponse(PluginBase):
    id: str
    enabled: bool
    installed_at: datetime
    
    class Config:
        from_attributes = True


class MemoryBase(BaseModel):
    content: str


class ShortTermMemoryCreate(MemoryBase):
    session_id: str
    role: str


class LongTermMemoryCreate(MemoryBase):
    importance: Optional[float] = 0.5


class ShortTermMemoryResponse(MemoryBase):
    id: int
    session_id: str
    role: str
    timestamp: datetime
    
    class Config:
        from_attributes = True


class LongTermMemoryResponse(MemoryBase):
    id: int
    importance: float
    created_at: datetime
    access_count: int
    last_access: datetime
    
    class Config:
        from_attributes = True


class PromptConfigBase(BaseModel):
    name: str
    content: str
    variables: Optional[str] = None


class PromptConfigCreate(PromptConfigBase):
    pass


class PromptConfigUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    is_active: Optional[bool] = None


class PromptConfigResponse(PromptConfigBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class BehaviorStats(BaseModel):
    total_interactions: int
    total_tools_used: int
    total_errors: int
    top_tools: List[Any]
    top_intents: List[Any]
    average_response_time: float


class ConfirmationRequest(BaseModel):
    confirmed: bool
    step: Optional[Dict[str, Any]] = None


class ExperienceBase(BaseModel):
    experience_type: str = Field(..., description="经验类型")
    title: str = Field(..., max_length=200, description="经验标题")
    content: str = Field(..., description="经验内容")
    trigger_conditions: str = Field(..., description="触发条件")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    source_task: Optional[str] = Field(default="general", description="来源任务")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")


class ExperienceCreate(ExperienceBase):
    pass


class ExperienceUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    trigger_conditions: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None


class ExperienceResponse(ExperienceBase):
    id: int
    usage_count: int = 0
    success_count: int = 0
    created_at: datetime
    last_access: datetime
    
    class Config:
        from_attributes = True


class ExperienceSearchParams(BaseModel):
    query: Optional[str] = None
    experience_type: Optional[str] = None
    min_confidence: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    source_task: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ExperienceExtractionRequest(BaseModel):
    session_id: str
    user_goal: str
    execution_steps: List[Dict[str, Any]]
    final_result: str
    status: str = Field(..., description="success or failure")


class ExperienceStatsResponse(BaseModel):
    total_experiences: int
    type_distribution: Dict[str, int]
    avg_confidence: float
    avg_success_rate: float
    total_usage: int
    total_success: int
    top_experiences: List[Dict[str, Any]]
